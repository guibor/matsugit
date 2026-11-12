;;; matsugit-tables.el --- Matsugit document authoring -*- lexical-binding: t; -*-

;; Copyright (c) 2026 MDF (guibor)
;; SPDX-License-Identifier: MIT

;;; Commentary:
;; Part of the matsugit Emacs package. See README.org in this directory.

;;; Code:

(require 'cl-lib)
(require 'json)
(require 'subr-x)
(require 'browse-url)
(require 'url)
(declare-function org-table-end "org-table" (&optional table-type))
(declare-function org-element-property "org-element" (property element))
(declare-function org-element-type "org-element" (element))
(declare-function org-element-context "org-element" (&optional element))
(declare-function org-element-lineage "org-element" (datum &optional types with-self))
(declare-function treesit-node-parent "treesit.c" (node))
(declare-function treesit-node-type "treesit.c" (node))

(require 'matsugit)
(defcustom matsugit-table-program nil "Optional table CLI override; nil uses matsugit-program." :type '(choice (const nil) string) :group 'matsugit)
(defcustom matsugit-table-ssh-host nil "SSH host for manual port forwarding when the browser is on another computer." :type '(choice (const nil) string) :group 'matsugit)
(defvar-local matsugit-table--process nil)
(defvar-local matsugit-table--recovery nil)
(defvar-local matsugit-table--grid-overlays nil)

(defun matsugit-table--org-bounds ()
  "Find a native table or explicit Markdown table export block in Org."
  (require 'org-element)
  (let* ((element (org-element-lineage (org-element-context)
                                      '(table export-block src-block example-block) t))
         (kind (org-element-type element)))
    (pcase kind
      ('table
       (save-excursion
         (goto-char (org-element-property :end element))
         (skip-chars-forward " \t\n")
         (when (or (org-element-property :tblfm element)
                   (let ((case-fold-search t)) (looking-at-p "#\\+TBLFM:")))
           (user-error "Use Org's native table commands for formula tables; visual edits cannot update formula references")))
       (cons (org-element-property :post-affiliated element)
             (save-excursion (goto-char (org-element-property :post-affiliated element))
                             (org-table-end))))
      ('export-block
       (unless (equal (downcase (or (org-element-property :type element) "")) "markdown")
         (user-error "Select a native Org table or a Markdown table export block"))
       (cons (org-element-property :post-affiliated element)
             (- (org-element-property :end element)
                (save-excursion
                  (goto-char (org-element-property :end element))
                  (let ((end (point))) (skip-chars-backward " \t\n")
                    (max 0 (1- (- end (point)))))))))
      (_ (user-error "Put point in an Org table, not a source/example block")))))

(defun matsugit-table--bounds ()
  "Return the selected region or contiguous pipe/grid table at point.
matsugit validates the selection with Pandoc before opening an editor."
  (cond
   ((use-region-p)
    (when (derived-mode-p 'org-mode)
      (save-excursion
        (goto-char (region-beginning))
        (skip-chars-forward " \t\n")
        (when (org-element-lineage (org-element-context) '(table) t)
          (matsugit-table--org-bounds))))
    (cons (region-beginning) (region-end)))
   ((derived-mode-p 'org-mode) (matsugit-table--org-bounds))
   (t
    (when (or (and (fboundp 'markdown-code-block-at-point-p)
                   (derived-mode-p 'markdown-mode) (markdown-code-block-at-point-p))
              (and (fboundp 'treesit-node-at)
                   (ignore-errors
                     (let ((node (treesit-node-at (point))))
                       (while (and node (not (member (treesit-node-type node)
                                                    '("fenced_code_block" "indented_code_block"))))
                         (setq node (treesit-node-parent node)))
                       node))))
      (user-error "This is a code block, not a table"))
    (cl-labels ((row-p ()
                  (or (looking-at-p "[ \t]*[+][-+=:]+")
                      (string-match-p "|" (buffer-substring-no-properties
                                            (line-beginning-position) (line-end-position))))))
      (save-excursion
        (beginning-of-line)
        (unless (row-p) (user-error "Put point in a Markdown pipe/grid table, or select one"))
        (let ((steps 0) start)
          (while (and (> (point) (point-min))
                      (save-excursion (forward-line -1) (row-p)))
            (when (> (cl-incf steps) 2000) (user-error "Table selection is too large"))
            (forward-line -1))
          (setq start (point))
          (while (and (< (point) (point-max)) (row-p))
            (when (> (cl-incf steps) 4000) (user-error "Table selection is too large"))
            (forward-line 1))
          (cons start (point))))))))

(defun matsugit-table--decorate (start end)
  "Keep an edited text grid monospaced, with a bounded local overlay."
  (setq matsugit-table--grid-overlays
        (cl-delete-if (lambda (overlay)
                        (when (or (not (overlay-buffer overlay))
                                  (and (< (overlay-start overlay) end) (> (overlay-end overlay) start)))
                          (delete-overlay overlay) t)) matsugit-table--grid-overlays))
  (save-excursion
    (goto-char start)
    (when (looking-at-p "[ \t]*[+][-+=:]+")
      (let ((overlay (make-overlay start end)))
        (overlay-put overlay 'face 'fixed-pitch)
        (overlay-put overlay 'help-echo "M-x matsugit-edit-table: edit or resume this table")
        (overlay-put overlay 'evaporate t)
        (push overlay matsugit-table--grid-overlays)))))

(defun matsugit-table--apply (buffer start end original replacement)
  "Replace a still-matching table, never an independently edited source."
  (unless (and (buffer-live-p buffer) (marker-position start) (marker-position end))
    (user-error "The source buffer is no longer available"))
  (with-current-buffer buffer
    (save-restriction
      (widen)
      (barf-if-buffer-read-only)
      (unless (equal original (buffer-substring-no-properties start end))
        (user-error "The source table changed while the visual editor was open"))
      (let ((position (marker-position start)))
        (undo-boundary)
        (atomic-change-group
          (goto-char position)
          (delete-region start end)
          (insert replacement))
        (undo-boundary)
        (matsugit-table--decorate position (+ position (length replacement)))
        (goto-char position)))))

(defun matsugit-table--ready (process data)
  "Open the session locally, or explain the explicit remote forwarding path."
  (let ((url (alist-get 'url data))
        (port (alist-get 'port data))
        (host (process-get process 'ssh-host)))
    (process-put process 'url url)
    (process-put process 'protocol (alist-get 'protocol data))
    (when-let ((timer (process-get process 'finish-timer))) (cancel-timer timer))
    (process-put process 'finish-timer nil)
    (process-put process 'save-unanswered nil)
    (if host
        (with-current-buffer (get-buffer-create "*Table editor connection*")
          (let ((inhibit-read-only t))
            (erase-buffer)
            (insert (format "On the computer running your browser:\n\nssh -N -L %d:127.0.0.1:%d %s\n\nOpen in that computer's browser:\n%s\n\nLeave the tunnel open until Save and Return.\n"
                            port port (shell-quote-argument host) url)))
          (special-mode)
          (display-buffer (current-buffer)))
      (browse-url url))))

(defun matsugit-table--request (process action callback)
  "Send ACTION to this local session asynchronously; call CALLBACK with data/error."
  (let ((url (process-get process 'url)))
    (unless (and (>= (or (process-get process 'protocol) 0) 2)
                 (stringp url)
                 (string-match "\\`\\(http://127\\.0\\.0\\.1:[0-9]+/\\)#\\([A-Za-z0-9_-]+\\)\\'" url))
      (user-error "This older/starting editor must use Save and Return in its browser"))
    (let ((endpoint (concat (match-string 1 url) "api/control"))
          (token (match-string 2 url)) response timer finished)
      (cl-labels ((finish (data err)
                    (unless finished
                      (setq finished t)
                      (when timer (cancel-timer timer))
                      (funcall callback data err))))
        (let ((url-request-method "POST")
              (url-request-data (json-encode `((action . ,action))))
              (url-request-extra-headers `(("Authorization" . ,(concat "Bearer " token))
                                           ("Content-Type" . "application/json")))
              (url-proxy-services nil))
          (setq response
                (url-retrieve
                 endpoint
                 (lambda (status)
                   (let ((response-buffer (current-buffer)))
                     (unwind-protect
			 (condition-case err
                             (progn
                               (when (plist-get status :error)
				 (error "Table editor connection failed"))
                               (goto-char (point-min))
                               (unless (re-search-forward "\r?\n\r?\n" nil t)
				 (error "Invalid table editor response"))
                               (let* ((json-object-type 'alist) (json-key-type 'symbol)
                                      (json-false nil)
                                      (data (json-read)))
				 (if (alist-get 'error data)
                                     (finish nil (alist-get 'error data))
                                   (finish data nil))))
                           (error (finish nil (error-message-string err))))
                       (when (buffer-live-p response-buffer)
			 (kill-buffer response-buffer))))) nil t t)))
        (unless finished
          (setq timer
                (run-at-time 8 nil
                             (lambda ()
                               (finish nil "Table editor request timed out; the source is unchanged")
                               (when (buffer-live-p response) (kill-buffer response))))))))))

(defun matsugit-table-save-checkpoint ()
  "Explicitly finish using the last acknowledged draft, not uncheckpointed typing."
  (interactive)
  (let ((process matsugit-table--process))
    (unless (and process (process-live-p process)) (user-error "No active table session"))
    (when (yes-or-no-p "Use the last saved browser draft? Very recent typing may be absent. ")
      (matsugit-table--request
       process "save-draft"
       (lambda (_data err) (when err (message "%s; resume the browser to recover" err)))))))

(defun matsugit-table-finish ()
  "Ask the browser to save its current content and end this editing session."
  (interactive)
  (let ((process matsugit-table--process))
    (unless (and process (process-live-p process)) (user-error "No active table session"))
    (if (process-get process 'save-unanswered)
        (matsugit-table-save-checkpoint)
      (when-let ((timer (process-get process 'finish-timer))) (cancel-timer timer))
      (matsugit-table--request
       process "save"
       (lambda (data err)
	 (cond (err (message "%s" err))
               ((alist-get 'attached data)
		(message "Save requested from browser...")
		(process-put process 'finish-timer
                             (run-at-time
                              12 nil
                              (lambda ()
				(when (process-live-p process)
                                  (process-put process 'save-unanswered t)
                                  (message "Browser did not answer. Run matsugit-edit-table again to choose the last checkpoint or resume. Source unchanged"))))))
               ((alist-get 'has_draft data)
		(when (and (buffer-live-p (process-get process 'source-buffer))
                           (yes-or-no-p "No active browser response. Save its last checkpoint? Recent typing may be absent. "))
                  (matsugit-table--request
                   process "save-draft" (lambda (_data error) (when error (message "%s" error))))))
               (t (message "No browser draft is available; resume the editor"))))))))

(defun matsugit-table--show-recovery (process)
  "Open saved output/draft separately, never overwrite the source on a conflict."
  (let* ((result (process-get process 'result))
         (draft (concat result ".draft.json")))
    (if (file-exists-p result)
        (find-file-other-window result)
      (unless (file-exists-p draft) (user-error "No saved table draft is available"))
      (let* ((json-object-type 'alist) (json-key-type 'symbol)
             (text (alist-get 'markdown (json-read-file draft)))
             (file (make-temp-file (expand-file-name "recovered-" (process-get process 'directory))
                                   nil (concat "." (file-name-extension result)) text)))
        (find-file-other-window file)))))

(defun matsugit-table--filter (process output)
  "Consume newline-delimited session events without evaluating agent output."
  (let ((text (concat (or (process-get process 'pending) "") output)) line)
    (while (string-match "\n" text)
      (setq line (substring text 0 (match-beginning 0))
            text (substring text (match-end 0)))
      (condition-case err
          (let* ((json-object-type 'alist) (json-key-type 'symbol)
                 (data (json-read-from-string line)))
            (when (equal (alist-get 'event data) "ready") (matsugit-table--ready process data)))
        (error (message "Table editor event: %s" (error-message-string err)))))
    (process-put process 'pending text)))

(defun matsugit-table--sentinel (process _event)
  "Apply saved output or retain recoverable edits on conflicts and failures."
  (when (and (memq (process-status process) '(exit signal))
             (not (process-get process 'handled)))
    (process-put process 'handled t)
    (when-let ((timer (process-get process 'finish-timer))) (cancel-timer timer))
    (let* ((buffer (process-get process 'source-buffer))
           (start (process-get process 'start)) (end (process-get process 'end))
           (directory (process-get process 'directory))
           (result (or (process-get process 'result)
                       (expand-file-name "result.md" directory)))
           (clean nil))
      (when (buffer-live-p buffer)
        (with-current-buffer buffer
          (when (eq matsugit-table--process process) (setq matsugit-table--process nil))))
      (condition-case err
          (cond
           ((and (eq (process-status process) 'exit) (= 0 (process-exit-status process))
                 (file-exists-p result))
            (let ((replacement (with-temp-buffer
                                 (insert-file-contents result) (buffer-string))))
              (matsugit-table--apply buffer start end (process-get process 'original) replacement)
              (setq clean t)
              (ignore-errors
                (let ((frame (process-get process 'frame)))
                  (when (frame-live-p frame) (select-frame-set-input-focus frame)))
                (pop-to-buffer buffer))
              (message "Table updated; the source file is not saved yet")))
           ((or (process-get process 'cancelled) (= 2 (process-exit-status process)))
            (setq clean t)
            (message "Table editing cancelled; source unchanged"))
           ((file-exists-p (concat result ".draft.json"))
            (message "Browser draft retained; matsugit-edit-table in the source buffer resumes it"))
           (t (display-buffer (process-get process 'log-buffer))
              (message "Table editor failed; source unchanged. Recovery files: %s" directory)))
        (error
         (when (file-exists-p result) (find-file-other-window result))
         (message "%s; edited table retained at %s" (error-message-string err) result)))
      (if (and (not clean) (buffer-live-p buffer)
               (or (file-exists-p result) (file-exists-p (concat result ".draft.json"))))
          (with-current-buffer buffer (setq matsugit-table--recovery process))
        (set-marker start nil) (set-marker end nil))
      (when clean
        (delete-directory directory t)
        (when (buffer-live-p (process-get process 'log-buffer))
          (kill-buffer (process-get process 'log-buffer)))))))

(defun matsugit-table--spawn (input result properties)
  "Start a new process for an existing source snapshot and its marker PROPERTIES."
  (let ((process (make-process :name "matsugit-table" :buffer nil
                               :stderr (alist-get 'log-buffer properties)
                               :command (list (or matsugit-table-program matsugit-program) "edit-table" input
                                              "--output" result "--no-open")
                               :coding 'utf-8-unix :connection-type 'pipe :noquery t)))
    (dolist (pair properties) (process-put process (car pair) (cdr pair)))
    (process-put process 'input input)
    (process-put process 'result result)
    (set-process-filter process #'matsugit-table--filter)
    (set-process-sentinel process #'matsugit-table--sentinel)
    (setq matsugit-table--process process matsugit-table--recovery nil)
    process))

(defun matsugit-table--manage ()
  "Resume, finish or discard the current buffer's existing session."
  (if (and matsugit-table--process (process-live-p matsugit-table--process))
      (pcase (completing-read "Table editor: " '("Save and return" "Resume editor" "Discard browser edits") nil t)
        ("Save and return" (matsugit-table-finish))
        ("Resume editor"
         (unless (>= (or (process-get matsugit-table--process 'protocol) 0) 2)
           (user-error "Use the existing browser tab for this older/starting session"))
         (matsugit-table--ready matsugit-table--process
                                  `((url . ,(process-get matsugit-table--process 'url))
                                    (port . ,(url-port (url-generic-parse-url (process-get matsugit-table--process 'url))))
                                    (protocol . 2))))
        ("Discard browser edits" (matsugit-cancel-table-editor)))
    (let ((old matsugit-table--recovery))
      (unless old (user-error "No table session to resume"))
      (pcase (completing-read "Recovered table: " '("Resume saved draft" "Open recovery separately" "Discard saved draft") nil t)
        ("Open recovery separately" (matsugit-table--show-recovery old))
        ("Discard saved draft"
         (when (yes-or-no-p "Discard this saved browser draft and its recovery files? ")
           (delete-directory (process-get old 'directory) t)
           (set-marker (process-get old 'start) nil) (set-marker (process-get old 'end) nil)
           (setq matsugit-table--recovery nil)))
        ("Resume saved draft"
         (if (file-exists-p (process-get old 'result))
             (matsugit-table--show-recovery old)
           (let ((properties (mapcar (lambda (key) (cons key (process-get old key)))
                                     '(source-buffer start end original directory frame ssh-host))))
             (push (cons 'log-buffer (generate-new-buffer "*Table editor log*")) properties)
             (matsugit-table--spawn (process-get old 'input) (process-get old 'result) properties))))))))

;;;###autoload
(defun matsugit-edit-table ()
  "Edit the Org or Markdown table at point in a separate local browser window.
Save and Return replaces only this table, as one undoable buffer edit. Merged
cells are saved as readable Pandoc grid tables, never hidden HTML source."
  (interactive)
  ;; Settle an exited process before deciding whether a recovery session exists.
  (when (and matsugit-table--process (not (process-live-p matsugit-table--process)))
    (matsugit-table--sentinel matsugit-table--process ""))
  (if (or (and matsugit-table--process (process-live-p matsugit-table--process))
          matsugit-table--recovery)
      (matsugit-table--manage)
    (barf-if-buffer-read-only)
    (pcase-let* ((`(,beg . ,end) (matsugit-table--bounds))
		 (original (buffer-substring-no-properties beg end))
		 (directory (make-temp-file "matsugit-table-" t))
		 (extension (if (derived-mode-p 'org-mode) ".org" ".md"))
		 (input (expand-file-name (concat "table" extension) directory))
		 (result (expand-file-name (concat "result" extension) directory))
		 (log (generate-new-buffer "*Table editor log*"))
		 (coding-system-for-write 'utf-8-unix))
      (when (> (string-bytes original) (* 1024 1024))
	(delete-directory directory) (user-error "Table exceeds 1 MiB"))
      (write-region original nil input nil 'silent)
      (set-file-modes input #o600)
      (condition-case err
          (matsugit-table--spawn
           input result
           `((source-buffer . ,(current-buffer)) (start . ,(copy-marker beg t))
             (end . ,(copy-marker end nil)) (original . ,original)
             (directory . ,directory) (result . ,result)
             (log-buffer . ,log) (frame . ,(selected-frame))
             (ssh-host . ,matsugit-table-ssh-host)))
	(error (delete-directory directory t) (kill-buffer log) (signal (car err) (cdr err))))
      (message "Opening visual table editor..."))))


(defun matsugit-cancel-table-editor ()
  "Cancel only this buffer's table-editor subprocess, without changing source."
  (interactive)
  (unless (and matsugit-table--process (process-live-p matsugit-table--process))
    (user-error "No table editor is running for this buffer"))
  (when (yes-or-no-p "Discard the browser edits and end this table session? ")
    (if (>= (or (process-get matsugit-table--process 'protocol) 0) 2)
        (matsugit-table--request
         matsugit-table--process "cancel" (lambda (_data err) (when err (message "%s" err))))
      (process-put matsugit-table--process 'cancelled t)
      (delete-process matsugit-table--process))))

(provide 'matsugit-tables)
;;; matsugit-tables.el ends here
