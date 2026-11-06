;;; matsugit-story.el --- Edit a deck's narrative -*- lexical-binding: t; -*-

;; Uses the same parser and structural operations as the browser workspace.
;; Source buffers own edits, Undo and Save; this buffer is only a projection.

(require 'cl-lib)
(require 'json)
(require 'subr-x)
(require 'button)

(defgroup matsugit-story nil "Narrative editing for Markdown and Org." :group 'tools)
(defcustom matsugit-story-node-program "node" "Node 22+ executable." :type 'string)
(defcustom matsugit-story-bridge
  (expand-file-name "../../codex-plugin/bundle/story-cli.mjs"
                    (file-name-directory (or load-file-name buffer-file-name)))
  "Bundled, editor-independent Story parser and operations." :type 'file)
(defcustom matsugit-story-agent-function nil
  "Function receiving SOURCE buffer, START, END and user REQUEST.
It must preserve the source and explicitly choose whether to submit to an agent."
  :type '(choice (const nil) function))
(defcustom matsugit-story-preview-function nil
  "Command to preview the deck, called in its source buffer." :type '(choice (const nil) function))
(defface matsugit-story-section '((t (:inherit font-lock-keyword-face :weight bold :height 1.2))) "Section transition." :group 'matsugit-story)
(defface matsugit-story-title '((t (:inherit default :weight bold))) "Slide title." :group 'matsugit-story)
(defface matsugit-story-claim '((t (:inherit shadow))) "Slide claim." :group 'matsugit-story)
(defface matsugit-story-takeaway '((t (:inherit success :weight bold))) "Slide takeaway." :group 'matsugit-story)

(defvar-local matsugit-story--source nil)
(defvar-local matsugit-story--projection nil)
(defvar-local matsugit-story--snapshot nil)
(defvar-local matsugit-story--tick nil)
(defvar-local matsugit-story--model nil)
(defvar-local matsugit-story--process nil)
(defvar-local matsugit-story--timer nil)
(defvar-local matsugit-story--walkthrough nil)
(defvar-local matsugit-story--compact nil)
(defvar-local matsugit-story--collapsed nil)
(defvar-local matsugit-story--selected nil)
(defvar-local matsugit-story--selection-overlay nil)
(defvar-local matsugit-story--anchor 0)

(defun matsugit-story--text ()
  (with-current-buffer matsugit-story--source
    (save-restriction (widen) (buffer-substring-no-properties (point-min) (point-max)))))

(defun matsugit-story--cancel ()
  (when (timerp matsugit-story--timer) (cancel-timer matsugit-story--timer))
  (setq matsugit-story--timer nil)
  (when (process-live-p matsugit-story--process)
    (let ((buffer (process-buffer matsugit-story--process)))
      (when-let ((timer (process-get matsugit-story--process 'timeout))) (cancel-timer timer))
      (set-process-sentinel matsugit-story--process #'ignore)
      (delete-process matsugit-story--process)
      (when (buffer-live-p buffer) (kill-buffer buffer))))
  (setq matsugit-story--process nil))

(defun matsugit-story--request (arguments callback)
  "Run ARGUMENTS without blocking Emacs; CALLBACK only sees current source."
  (unless (buffer-live-p matsugit-story--source) (user-error "The source buffer is closed"))
  (unless (and (executable-find matsugit-story-node-program) (file-readable-p matsugit-story-bridge))
    (user-error "Install/update matsugit and Node 22+; missing Story bridge: %s" matsugit-story-bridge))
  (matsugit-story--cancel)
  (let* ((view (current-buffer)) (source matsugit-story--source)
         (snapshot (matsugit-story--text))
         (tick (with-current-buffer source (buffer-chars-modified-tick)))
         (org (with-current-buffer source (or (derived-mode-p 'org-mode) (string-match-p "\\.org\\'" (or buffer-file-name "")))))
         (output (generate-new-buffer " *matsugit-story-process*"))
         (default-directory temporary-file-directory))
    (when (> (string-bytes (encode-coding-string snapshot 'utf-8)) (* 2 1024 1024))
      (kill-buffer output) (user-error "Story supports documents up to 2 MiB"))
    (setq header-line-format "matsugit Story | Updating...")
    (setq matsugit-story--process
          (make-process
           :name "matsugit-story" :buffer output :noquery t :connection-type 'pipe
           :coding 'utf-8-unix :command (list matsugit-story-node-program matsugit-story-bridge)
           :sentinel
           (lambda (process _event)
             (when (memq (process-status process) '(exit signal))
               (when-let ((timer (process-get process 'timeout))) (cancel-timer timer))
               (unwind-protect
                   (when (and (buffer-live-p view) (buffer-live-p source))
                     (with-current-buffer view
                       (when (eq process matsugit-story--process)
                         (setq matsugit-story--process nil)
                         (condition-case err
                             (if (/= 0 (process-exit-status process))
                                 (error "%s" (with-current-buffer output (string-trim (buffer-string))))
                               (if (/= tick (with-current-buffer source (buffer-chars-modified-tick)))
                                   (progn (setq header-line-format "matsugit Story | Source changed; refreshing")
                                          (matsugit-story-refresh))
                                 (let ((data (with-current-buffer output
                                               (goto-char (point-min))
                                               (json-parse-buffer :object-type 'alist :array-type 'list :null-object nil :false-object nil))))
                                   (funcall callback data snapshot tick))))
                           (error (setq header-line-format (concat "matsugit Story | " (error-message-string err)))
                                  (message "Story: %s" (error-message-string err)))))))
                 (when (buffer-live-p output) (kill-buffer output)))))))
    (let ((process matsugit-story--process))
      (process-put process 'timeout
                   (run-at-time 30 nil (lambda () (when (process-live-p process) (delete-process process))))))
    (process-send-string matsugit-story--process
                         (json-serialize (append `((source . ,snapshot) (org . ,(if org t :false))) arguments)))
    (process-send-eof matsugit-story--process)))

(defun matsugit-story--node ()
  (or (get-text-property (point) 'matsugit-node)
      (let ((next (next-single-property-change (point) 'matsugit-node)))
        (and next (get-text-property next 'matsugit-node)))
      (user-error "No slide or section here")))

(defun matsugit-story--goto (from)
  (goto-char (point-min))
  (let ((position (point-min)) found)
    (while (and (< position (point-max)) (not found))
      (let ((node (get-text-property position 'matsugit-node)))
        (when (and node (= from (alist-get 'from node))) (setq found position)))
      (setq position (or (next-single-property-change position 'matsugit-node) (point-max))))
    (when found (goto-char found))))

(defun matsugit-story--button (label help command node)
  (insert-text-button label 'help-echo help 'follow-link t
                      'action (lambda (_button)
                                (matsugit-story--goto (alist-get 'from node))
                                (call-interactively command))))

(defun matsugit-story--render ()
  (let ((inhibit-read-only t) (position matsugit-story--anchor))
    (erase-buffer)
    (insert (propertize (buffer-name matsugit-story--source) 'face 'bold) "\n\n")
    (dolist (item '(("Overview / Walkthrough" . matsugit-story-toggle-view)
                    ("Compact" . matsugit-story-toggle-size)
                    ("+ Slide" . matsugit-story-insert)))
      (let ((command (cdr item)))
        (insert-text-button (car item) 'follow-link t 'action (lambda (_) (call-interactively command))))
      (insert "   "))
    (insert-text-button "+ Section" 'follow-link t 'action (lambda (_) (matsugit-story-insert t)))
    (insert "\n\n")
    (dolist (node (alist-get 'nodes matsugit-story--model))
      (unless (and (not matsugit-story--walkthrough)
                   (member (alist-get 'parent node) matsugit-story--collapsed))
        (let* ((start (point)) (section (equal (alist-get 'kind node) "section"))
               (indent (if (or section matsugit-story--walkthrough) "" "  ")))
          (when matsugit-story--walkthrough
            (insert (propertize (make-string (min 78 (max 20 (- (window-body-width) 4))) ?-) 'face 'shadow) "\n\n"))
          (insert indent (if section (if (member (alist-get 'from node) matsugit-story--collapsed) "+ " "- ")
                           (format "%02d  " (alist-get 'number node))))
          (insert (propertize (alist-get 'title node) 'face
                              (cond (section 'matsugit-story-section)
                                    (matsugit-story--walkthrough '(:inherit matsugit-story-title :height 1.35))
                                    (t 'matsugit-story-title))))
          (insert "  ")
          (matsugit-story--button "\u270e" "Edit title" #'matsugit-story-edit-title node)
          (insert " ") (matsugit-story--button "\u2195" "Move to slide or section" #'matsugit-story-move node)
          (unless section (insert " ") (matsugit-story--button "\u2728" "Ask agent about this slide" #'matsugit-story-ask-agent node))
          (insert "\n")
          (dolist (claim (alist-get 'claims node))
            (insert indent "    " (propertize (alist-get 'label claim) 'face 'matsugit-story-claim) " ")
            (matsugit-story--button "\u270e" "Edit claim" #'matsugit-story-edit-claim node) (insert "\n"))
          (dolist (takeaway (alist-get 'takeaways node))
            (insert indent "    " (propertize (concat "=> " (alist-get 'label takeaway)) 'face 'matsugit-story-takeaway) " ")
            (matsugit-story--button "\u270e" "Edit takeaway" #'matsugit-story-edit-takeaway node) (insert "\n"))
          (when (and (not section) (alist-get 'empty node)) (insert indent "    " (propertize "Empty slide" 'face 'shadow) "\n"))
          (when (> (or (alist-get 'continuations node) 0) 0)
            (insert indent (propertize (format "    +%d continuation(s)\n" (alist-get 'continuations node)) 'face 'shadow)))
          (insert (if matsugit-story--walkthrough (if matsugit-story--compact "\n" "\n\n\n\n") "\n"))
          (add-text-properties start (point) `(matsugit-node ,node mouse-face highlight)))))
    (setq header-line-format
          (format "matsugit Story | %s | %d sections, %d slides | %s"
                  (if matsugit-story--walkthrough (if matsugit-story--compact "Compact walkthrough" "Walkthrough") "Overview")
                  (alist-get 'sections matsugit-story--model) (alist-get 'slides matsugit-story--model)
                  (if (buffer-modified-p matsugit-story--source) "Unsaved source edits" "Saved source")))
    (set-buffer-modified-p nil)
    (matsugit-story--goto position)
    (matsugit-story--highlight)))

(defun matsugit-story--highlight ()
  (when (overlayp matsugit-story--selection-overlay) (delete-overlay matsugit-story--selection-overlay))
  (when matsugit-story--selected
    (save-excursion
      (matsugit-story--goto matsugit-story--selected)
      (let ((end (or (next-single-property-change (point) 'matsugit-node) (point-max))))
        (setq matsugit-story--selection-overlay (make-overlay (point) end))
        (overlay-put matsugit-story--selection-overlay 'face 'highlight)))))

(defun matsugit-story-refresh ()
  "Refresh the projection without saving or reverting the source."
  (interactive)
  (matsugit-story--request '((action . "model"))
                          (lambda (data snapshot tick)
                            (setq matsugit-story--model data matsugit-story--snapshot snapshot matsugit-story--tick tick)
                            (matsugit-story--render))))

(defun matsugit-story--source-changed (&rest _)
  (when (buffer-live-p matsugit-story--projection)
    (with-current-buffer matsugit-story--projection
      (when (timerp matsugit-story--timer) (cancel-timer matsugit-story--timer))
      (let ((view (current-buffer)))
        (setq matsugit-story--timer
              (run-at-time .4 nil (lambda () (when (buffer-live-p view)
                                              (with-current-buffer view (matsugit-story-refresh))))))))))

(defun matsugit-story--apply (data snapshot tick)
  (let ((change (alist-get 'change data)) (source matsugit-story--source))
    (when change
      (with-current-buffer source
        (when (or buffer-read-only (/= tick (buffer-chars-modified-tick))
                  (not (equal snapshot (save-restriction (widen) (buffer-substring-no-properties (point-min) (point-max))))))
          (user-error "Source changed; nothing applied. Refresh Story"))
        (when (and buffer-file-name (not (verify-visited-file-modtime source)))
          (user-error "File changed on disk; reconcile it in the source buffer first"))
        (save-restriction
          (widen) (undo-boundary)
          (atomic-change-group
            (goto-char (1+ (alist-get 'from change)))
            (delete-region (point) (1+ (alist-get 'to change)))
            (insert (alist-get 'insert change)))
          (undo-boundary)))
      (setq matsugit-story--anchor (alist-get 'anchor data)
            matsugit-story--selected nil))
    (matsugit-story-refresh)))

(defun matsugit-story--mutate (arguments)
  (unless (and matsugit-story--model (equal matsugit-story--snapshot (matsugit-story--text)))
    (matsugit-story-refresh) (user-error "Story is updating; retry after it refreshes"))
  (matsugit-story--request arguments #'matsugit-story--apply))

(defun matsugit-story-edit-title ()
  "Edit the title without disturbing its attributes or body."
  (interactive)
  (let ((node (matsugit-story--node)))
    (matsugit-story--mutate `((action . "edit") (from . ,(alist-get 'from node))
                            (text . ,(read-string "Title: " (alist-get 'title node)))))))

(defun matsugit-story--edit-field (field)
  (let* ((node (matsugit-story--node)) (items (alist-get field node)))
    (if (and (eq field 'claims) (not items) (equal (alist-get 'kind node) "slide"))
        (matsugit-story--mutate `((action . "claim") (from . ,(alist-get 'from node))))
      (unless items (user-error "No %s here; add it in the source" field))
      (let* ((choices (cl-loop for item in items for n from 1 collect (cons (format "%d: %s" n (alist-get 'label item)) item)))
             (item (if (= 1 (length choices)) (cdar choices) (cdr (assoc (completing-read "Field: " choices nil t) choices)))))
        (matsugit-story--mutate `((action . "edit") (kind . ,(alist-get 'kind item)) (from . ,(alist-get 'from item))
                                (text . ,(read-string "Text: " (alist-get 'label item)))))))))
(defun matsugit-story-edit-claim () "Edit a claim, or insert one." (interactive) (matsugit-story--edit-field 'claims))
(defun matsugit-story-edit-takeaway () "Edit a takeaway." (interactive) (matsugit-story--edit-field 'takeaways))

(defun matsugit-story-insert (section)
  "Insert an empty slide with title/claim; with prefix SECTION, insert a section."
  (interactive "P")
  (let ((from (condition-case nil (alist-get 'from (matsugit-story--node)) (user-error 0))))
    (matsugit-story--mutate `((action . "insert") (from . ,from) (kind . ,(if section "section" "slide"))
                            (title . ,(read-string (if section "Section: " "Slide title: ")))
                            (claim . ,(if section "" (read-string "Claim (optional): ")))))))

(defun matsugit-story-move ()
  "Move a whole slide or section to a searchable destination."
  (interactive)
  (let ((from (alist-get 'from (matsugit-story--node))))
    (matsugit-story--request `((action . "destinations") (from . ,from))
     (lambda (data snapshot _tick)
       (let* ((choices (mapcar (lambda (item) (cons (format "%s | %s | %s" (alist-get 'label item) (alist-get 'context item) (alist-get 'claim item)) item)) (alist-get 'destinations data)))
              (_ (unless choices (user-error "No other destination")))
              (target (cdr (assoc (completing-read "Move to: " choices nil t) choices)))
              (placements (mapcar (lambda (p) (cons (cadr p) (car p))) (alist-get 'placements target)))
              (placement (cdr (assoc (completing-read "Position: " placements nil t) placements))))
         (unless (equal snapshot (matsugit-story--text)) (user-error "Source changed; refresh before moving"))
         (matsugit-story--mutate `((action . "move") (from . ,from) (target . ,(alist-get 'from target)) (placement . ,placement))))))))

(defun matsugit-story-move-up () "Move this item before its previous sibling." (interactive) (matsugit-story--mutate `((action . "adjacent") (from . ,(alist-get 'from (matsugit-story--node))) (direction . -1))))
(defun matsugit-story-move-down () "Move this item after its next sibling." (interactive) (matsugit-story--mutate `((action . "adjacent") (from . ,(alist-get 'from (matsugit-story--node))) (direction . 1))))

(defun matsugit-story-source ()
  "Visit the selected item's original source."
  (interactive)
  (let ((from (alist-get 'from (matsugit-story--node))) (source matsugit-story--source))
    (pop-to-buffer source) (widen) (goto-char (1+ from))))
(defun matsugit-story-save () "Save through the source buffer's normal checks." (interactive) (with-current-buffer matsugit-story--source (save-buffer)) (matsugit-story-refresh))
(defun matsugit-story-undo () "Undo one source operation." (interactive) (with-current-buffer matsugit-story--source (undo-only 1)) (matsugit-story-refresh))
(defun matsugit-story-redo () "Redo one source operation." (interactive) (with-current-buffer matsugit-story--source (undo-redo 1)) (matsugit-story-refresh))
(defun matsugit-story-preview () "Preview with the configured integration." (interactive) (unless matsugit-story-preview-function (user-error "Configure matsugit-story-preview-function")) (with-current-buffer matsugit-story--source (call-interactively matsugit-story-preview-function)))
(defun matsugit-story-ask-agent ()
  "Send this slide's bounds and an explicit request to the configured agent."
  (interactive)
  (unless matsugit-story-agent-function (user-error "Configure matsugit-story-agent-function"))
  (unless (equal matsugit-story--snapshot (matsugit-story--text)) (user-error "Refresh Story before asking the agent"))
  (let ((node (matsugit-story--node)))
    (unless (equal (alist-get 'kind node) "slide") (user-error "Choose a slide"))
    (let ((request (read-string "Edit this slide: ")))
      (unless (equal matsugit-story--snapshot (matsugit-story--text)) (user-error "Source changed; refresh before asking the agent"))
      (funcall matsugit-story-agent-function matsugit-story--source
               (1+ (alist-get 'from node)) (1+ (alist-get 'end node)) request))))

(defun matsugit-story-toggle-view ()
  "Toggle Overview and Walkthrough without losing the current slide."
  (interactive)
  (setq matsugit-story--anchor (condition-case nil (alist-get 'from (matsugit-story--node)) (user-error 0))
        matsugit-story--walkthrough (not matsugit-story--walkthrough))
  (matsugit-story--render))
(defun matsugit-story-toggle-size ()
  "Toggle compact walkthrough spacing without losing the current slide."
  (interactive)
  (setq matsugit-story--anchor (condition-case nil (alist-get 'from (matsugit-story--node)) (user-error 0))
        matsugit-story--compact (not matsugit-story--compact))
  (matsugit-story--render))
(defun matsugit-story-toggle-section ()
  "Fold this section in Overview without changing the source."
  (interactive)
  (let* ((node (matsugit-story--node)) (from (if (equal (alist-get 'kind node) "section") (alist-get 'from node) (alist-get 'parent node))))
    (unless from (user-error "This slide has no section"))
    (setq matsugit-story--collapsed (if (member from matsugit-story--collapsed) (delete from matsugit-story--collapsed) (cons from matsugit-story--collapsed)) matsugit-story--anchor from)
    (matsugit-story--render)))
(defun matsugit-story-clear-selection () "Clear selection; navigation returns to scrolling." (interactive) (setq matsugit-story--selected nil) (matsugit-story--highlight))
(defun matsugit-story-select () "Select the item at point." (interactive) (setq matsugit-story--selected (alist-get 'from (matsugit-story--node))) (matsugit-story--highlight))
(defun matsugit-story--navigate (direction &optional section)
  (let* ((nodes (cl-remove-if-not (lambda (node) (and (or (not section) (equal (alist-get 'kind node) "section"))
                                                        (or matsugit-story--walkthrough (not (member (alist-get 'parent node) matsugit-story--collapsed)))))
                                (alist-get 'nodes matsugit-story--model)))
         (from (condition-case nil (alist-get 'from (matsugit-story--node)) (user-error -1)))
         (next (if (> direction 0) (cl-find-if (lambda (n) (> (alist-get 'from n) from)) nodes)
                 (car (last (cl-remove-if-not (lambda (n) (< (alist-get 'from n) from)) nodes))))))
    (when next
      (setq matsugit-story--anchor (alist-get 'from next))
      (matsugit-story--goto matsugit-story--anchor)
      (if matsugit-story--selected (setq matsugit-story--selected matsugit-story--anchor)
        (when-let ((window (get-buffer-window (current-buffer)))) (set-window-start window (point))))
      (matsugit-story--highlight))))
(defun matsugit-story-next () "Browse next, or move an existing selection." (interactive) (matsugit-story--navigate 1))
(defun matsugit-story-previous () "Browse previous, or move an existing selection." (interactive) (matsugit-story--navigate -1))
(defun matsugit-story-next-section () "Browse the next section." (interactive) (matsugit-story--navigate 1 t))
(defun matsugit-story-previous-section () "Browse the previous section." (interactive) (matsugit-story--navigate -1 t))
(defun matsugit-story-click (event)
  "Select a clicked row, or clear selection on the background."
  (interactive "e") (mouse-set-point event)
  (cond ((button-at (point)) (push-button))
        ((get-text-property (point) 'matsugit-node) (matsugit-story-select))
        (t (matsugit-story-clear-selection))))

(defun matsugit-story--cleanup ()
  (matsugit-story--cancel)
  (when (buffer-live-p matsugit-story--source)
    (with-current-buffer matsugit-story--source
      (remove-hook 'after-change-functions #'matsugit-story--source-changed t)
      (remove-hook 'after-save-hook #'matsugit-story--source-changed t)
      (setq matsugit-story--projection nil))))
(defvar matsugit-story-mode-map
  (let ((map (make-sparse-keymap)))
    (dolist (pair '(("j" . matsugit-story-next) ("k" . matsugit-story-previous)
                    ("<down>" . matsugit-story-next) ("<right>" . matsugit-story-next)
                    ("<up>" . matsugit-story-previous) ("<left>" . matsugit-story-previous)
                    ("l" . matsugit-story-next-section) ("h" . matsugit-story-previous-section)
                    ("RET" . matsugit-story-select) ("<escape>" . matsugit-story-clear-selection)
                    ("<mouse-1>" . matsugit-story-click) ("TAB" . matsugit-story-toggle-section)
                    ("e" . matsugit-story-edit-title) ("c" . matsugit-story-edit-claim) ("t" . matsugit-story-edit-takeaway)
                    ("a" . matsugit-story-insert) ("m" . matsugit-story-move)
                    ("M-<up>" . matsugit-story-move-up) ("M-<down>" . matsugit-story-move-down)
                    ("v" . matsugit-story-toggle-view) ("z" . matsugit-story-toggle-size)
                    ("o" . matsugit-story-source) ("g" . matsugit-story-refresh) ("s" . matsugit-story-save)
                    ("C-x C-s" . matsugit-story-save) ("u" . matsugit-story-undo) ("C-r" . matsugit-story-redo)
                    ("A" . matsugit-story-ask-agent) ("p" . matsugit-story-preview) ("q" . quit-window)))
      (define-key map (kbd (car pair)) (cdr pair))) map))
(define-derived-mode matsugit-story-mode special-mode "Story"
  "Narrative projection; all edits belong to its Markdown/Org source buffer."
  (setq-local truncate-lines nil)
  (visual-line-mode 1)
  (add-hook 'kill-buffer-hook #'matsugit-story--cleanup nil t))

;;;###autoload
(defun matsugit-story ()
  "Open the current Markdown/Org buffer as an editable narrative overview."
  (interactive)
  (if (derived-mode-p 'matsugit-story-mode) (matsugit-story-refresh)
    (let* ((source (current-buffer))
           (view (if (buffer-live-p matsugit-story--projection) matsugit-story--projection
                   (generate-new-buffer (format "*Story: %s*" (buffer-name))))))
      (setq-local matsugit-story--projection view)
      (add-hook 'after-change-functions #'matsugit-story--source-changed nil t)
      (add-hook 'after-save-hook #'matsugit-story--source-changed nil t)
      (with-current-buffer view
        (unless (derived-mode-p 'matsugit-story-mode) (matsugit-story-mode))
        (setq matsugit-story--source source)
        (matsugit-story-refresh))
      (pop-to-buffer view))))

(provide 'matsugit-story)
;;; matsugit-story.el ends here
