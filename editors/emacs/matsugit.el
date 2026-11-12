;;; matsugit.el --- Matsugit document authoring -*- lexical-binding: t; -*-

;; Version: 0.1.0
;; Package-Requires: ((emacs "29.1"))
;; URL: https://github.com/guibor/matsugit
;; Keywords: text, outlines, multimedia

;; Copyright (c) 2026 MDF (guibor)
;; SPDX-License-Identifier: MIT

;;; Commentary:
;; Part of the matsugit Emacs package. See README.org in this directory.
;; Load this library, then enable matsugit-mode in an Org or Markdown buffer.
;; Rendering stays in the external CLI; loading never starts it or publishes.

;;; Code:

(require 'cl-lib)
(require 'subr-x)
(require 'json)
(autoload 'compilation-start "compile")
(autoload 'browse-url-of-file "browse-url")
(autoload 'matsugit-mode "matsugit-authoring" "Author a Markdown or Org deck." t)
(autoload 'matsugit-authoring-mode "matsugit-authoring" "Author a Markdown or Org deck." t)
(autoload 'matsugit-insert "matsugit-authoring" "Insert a slide element." t)
(autoload 'matsugit-insert-menu "matsugit-authoring" "Insert a slide block." t)
(autoload 'matsugit-new-deck "matsugit-authoring" "Start a deck in an empty source buffer." t)
(autoload 'matsugit-open-browser "matsugit-browser" "Open the editable workspace." t)
(autoload 'matsugit-story "matsugit-story" "Edit the narrative in Emacs." t)
(autoload 'matsugit-edit-table "matsugit-tables" "Edit the table at point visually." t)
(autoload 'matsugit-insert-agent-comment "matsugit-comments" "Insert an agent review comment." t)
(autoload 'matsugit-delete-agent-comment "matsugit-comments" "Delete the review comment at point." t)
(defvar matsugit-story-preview-function)

(defgroup matsugit nil "Documents and slides from one source." :group 'tools)
(defcustom matsugit-program "matsugit" "Matsugit CLI executable." :type 'string :group 'matsugit)
(defcustom matsugit-remote-program "matsugit" "CLI executable on a TRAMP source host." :type 'string :group 'matsugit)
(defcustom matsugit-theme-directories nil "Directories containing installed theme packs." :type '(repeat directory) :group 'matsugit)

(with-eval-after-load 'matsugit-story
  (unless matsugit-story-preview-function
    (setq matsugit-story-preview-function #'matsugit-preview-slides)))
(defvar-local matsugit-target-repo nil
  "Publishing checkout; nil uses matsugit.json or the source repository.")
(defvar-local matsugit-target nil
  "Named publishing target; nil uses the project or host default.")
(defvar-local matsugit-theme nil
  "Theme override; nil uses project/global settings, then the launcher default.")

(defconst matsugit--recipes
  '("cover" "statement" "summary" "metrics" "exhibit" "evidence" "table"
    "okr-summary" "okr-objective"
    "comparison" "process" "d2" "timeline" "quotation" "decision" "chart"
    "implication" "mapping" "annotated" "assertion" "section" "canvas")
  "Theme-independent slide recipes supplied by the shared renderer.")

(defun matsugit-convert-string (text from to)
  "Convert TEXT FROM one source format TO another without executing code."
  (with-temp-buffer
    (insert text)
    (let* ((coding-system-for-read 'utf-8-unix)
          (coding-system-for-write 'utf-8-unix)
          (status (call-process-region (point-min) (point-max) matsugit-program
                                       t t nil "convert" "--from" from "--to" to)))
      (unless (and (integerp status) (zerop status))
        (user-error "matsugit conversion failed: %s"
                    (string-trim (buffer-string))))
      (buffer-string))))

(defun matsugit-configure-project (repo theme)
  "Persist REPO and THEME for this source project using directory locals."
  (interactive
   (list (read-directory-name "Publishing checkout: ")
         (completing-read "Theme: " (matsugit--themes) nil t)))
  (require 'files-x)
  (add-dir-local-variable nil 'matsugit-target-repo (expand-file-name repo))
  (add-dir-local-variable nil 'matsugit-theme theme)
  (setq-local matsugit-target-repo (expand-file-name repo))
  (setq-local matsugit-theme theme))

(defun matsugit--themes ()
  "List theme packs in the explicitly configured search directories."
  (delete-dups (cons "default"
    (cl-loop for root in matsugit-theme-directories
             append (mapcar (lambda (file) (file-name-nondirectory (directory-file-name (file-name-directory file))))
                            (file-expand-wildcards (expand-file-name "*/theme.json" root)))))))

(defun matsugit--source ()
  (unless (and buffer-file-name
               (member (downcase (or (file-name-extension buffer-file-name) ""))
                       '("md" "markdown" "org" "qmd")))
    (user-error "Visit a Markdown, Org, or Quarto file first"))
  (when (buffer-modified-p) (save-buffer))
  buffer-file-name)

(defvar-local matsugit--preview-target nil
  "Preview file, possibly remote, to open after successful compilation.")

(defun matsugit--open-preview (target)
  "Open TARGET locally, copying a remote preview's complete asset bundle."
  (if (file-regular-p target)
      (let ((local-target target))
        (when (file-remote-p target)
          (let ((directory (make-temp-file "matsugit-preview-local-" t)))
            (copy-directory (file-name-directory target) directory nil t t)
            (setq local-target
                  (expand-file-name (file-name-nondirectory target) directory))))
        (browse-url-of-file local-target))
    (message "matsugit finished but preview is missing: %s" target)))

(defun matsugit--preview-finished (buffer status)
  "Schedule BUFFER's requested preview after successful render STATUS."
  (when (buffer-live-p buffer)
    (with-current-buffer buffer
      (let ((target matsugit--preview-target))
        (setq matsugit--preview-target nil)
        (when (and target (string-match-p "\\`finished" status))
          ;; TRAMP file operations must run outside its process sentinel.
          (run-at-time 0 nil #'matsugit--open-preview target))))))

(defun matsugit--command (args)
  "Build a shell command for ARGS on the host of `default-directory'.
Resolve the remote launcher there and strip TRAMP prefixes only for that host."
  (let* ((remote (file-remote-p default-directory))
         (program (if remote
                      (file-local-name
                       (expand-file-name (concat remote matsugit-remote-program)
                                         default-directory))
                    matsugit-program)))
    (mapconcat
     #'shell-quote-argument
     (cons program
           (mapcar (lambda (arg)
                     (if-let ((host (file-remote-p arg)))
                         (if (equal host remote)
                             (file-local-name arg)
                           (user-error "matsugit path belongs to a different host: %s" arg))
                       arg))
                   args))
     " ")))

(defun matsugit--run (args &optional preview-target)
  "Run ARGS asynchronously, showing progress in a compilation buffer."
  (let ((buffer (get-buffer "*matsugit*")))
    (when (and buffer (get-buffer-process buffer))
      (user-error "A matsugit operation is already running")))
  (let ((buffer
         (compilation-start
          (matsugit--command args)
          'compilation-mode (lambda (_) "*matsugit*"))))
    (with-current-buffer buffer
      (setq-local matsugit--preview-target preview-target)
      (add-hook 'compilation-finish-functions #'matsugit--preview-finished nil t))
    buffer))

(defun matsugit--options ()
  (append (when matsugit-target-repo
            (list "--repo" (expand-file-name matsugit-target-repo)))
          (when matsugit-theme (list "--theme" matsugit-theme))))

(defun matsugit--preview (view)
  "Render on the source host and open VIEW locally, without publication."
  (let* ((source (matsugit--source))
         (default-directory (file-name-directory source))
         (output (if (file-remote-p source)
                     (make-nearby-temp-file "matsugit-preview-" t)
                   (make-temp-file "matsugit-preview-" t))))
    (matsugit--run
     (append (list "render" source "--output" output)
             (when (equal view "handout.html") '("--handout"))
             (matsugit--options))
     (expand-file-name view output))))

;;;###autoload
(defun matsugit-preview-document ()
  "Render on the source host and open the document, without publication."
  (interactive)
  (matsugit--preview "index.html"))

;;;###autoload
(defun matsugit-preview-slides ()
  "Render on the source host and open the deck, without publication."
  (interactive)
  (matsugit--preview "slides.html"))

(defalias 'matsugit-preview #'matsugit-preview-document)

;;;###autoload
(defun matsugit-preview-handout ()
  "Preview slides in reading order with presenter notes, without publishing."
  (interactive)
  (matsugit--preview "handout.html"))

;;;###autoload
(defun matsugit-select-theme (theme)
  "Select THEME for previews and exports in this buffer only."
  (interactive (list (completing-read "Theme: " (matsugit--themes) nil t)))
  (setq-local matsugit-theme theme)
  (message "matsugit theme: %s (buffer only)" theme))

;;;###autoload
(defun matsugit-select-target (target)
  "Select a configured publishing TARGET for this buffer only."
  (interactive
   (list (with-temp-buffer
           (unless (zerop (call-process matsugit-program nil t nil "target" "list"))
             (user-error "Cannot list targets: %s" (buffer-string)))
           (goto-char (point-min))
           (let* ((json-object-type 'alist)
                  (json-key-type 'string)
                  (data (json-read)))
             (completing-read "Publishing target (empty: default): "
                              (mapcar #'car (cdr (assoc "targets" data))) nil t)))))
  (setq-local matsugit-target (unless (string-empty-p target) target))
  (message "Publishing target: %s" (or matsugit-target "project/host default")))

;;;###autoload
(defun matsugit-export (format output sync-folder)
  "Export FORMAT to OUTPUT, or with prefix to the configured SYNC-FOLDER.
Never publishes to Git or connects a cloud account."
  (interactive
   (let* ((format (completing-read "Export format: " '("pptx" "pdf" "html" "zip") nil t))
          (sync current-prefix-arg))
     (list format (unless sync (read-file-name "Export to: " nil
                             (concat (file-name-base (or buffer-file-name "deck")) "." format))) sync)))
  (matsugit--run
   (append (list "export" (matsugit--source) "--format" format)
           (if sync-folder '("--sync-folder") (list "--output" (expand-file-name output)))
           (when matsugit-theme (list "--theme" matsugit-theme)))))

;;;###autoload
(defun matsugit-insert-template (name)
  "Insert a complete slide recipe NAME, using the buffer's source format."
  (interactive (list (completing-read "Slide component: "
                     matsugit--recipes nil t)))
  (barf-if-buffer-read-only)
  (unless (or (derived-mode-p 'org-mode 'markdown-mode 'markdown-ts-mode 'gfm-mode
                             'markdown-modern-mode 'md-mode 'md-ts-mode 'quarto-mode
                            )
              (member (downcase (or (file-name-extension (or buffer-file-name "")) ""))
                      '("org" "md" "markdown" "qmd")))
    (user-error "Use an Org or Markdown source buffer"))
  (let* ((format (if (or (derived-mode-p 'org-mode)
                        (equal (downcase (or (file-name-extension (or buffer-file-name "")) "")) "org"))
                     "org" "markdown"))
         (text (with-temp-buffer
                (let ((status (call-process matsugit-program nil t nil
                                            "template" name "--fragment" "--format" format)))
                  (unless (and (integerp status) (zerop status))
                    (user-error "matsugit template failed: %s" (buffer-string)))
                  (buffer-string)))))
    (atomic-change-group
      (unless (bolp) (insert "\n"))
      (unless (or (bobp) (save-excursion (forward-line -1) (looking-at-p "[ \t]*$")))
        (insert "\n"))
      (insert text))))

(defmacro matsugit--recipe-command (name)
  "Define a discoverable interactive insert command for recipe NAME."
  `(defun ,(intern (concat "matsugit-insert-" name "-slide")) ()
     ,(format "Insert the %s slide recipe in Org or Markdown syntax." name)
     (interactive)
     (matsugit-insert-template ,name)))

(matsugit--recipe-command "cover")
(matsugit--recipe-command "statement")
(matsugit--recipe-command "summary")
(matsugit--recipe-command "okr-summary")
(matsugit--recipe-command "okr-objective")
(matsugit--recipe-command "metrics")
(matsugit--recipe-command "exhibit")
(matsugit--recipe-command "evidence")
(matsugit--recipe-command "table")
(matsugit--recipe-command "comparison")
(matsugit--recipe-command "process")
(matsugit--recipe-command "d2")
(matsugit--recipe-command "timeline")
(matsugit--recipe-command "quotation")
(matsugit--recipe-command "decision")
(matsugit--recipe-command "chart")
(matsugit--recipe-command "implication")
(matsugit--recipe-command "mapping")
(matsugit--recipe-command "annotated")

;;;###autoload
(defun matsugit-lint ()
  "Check source structure and slide density; does not publish or execute code."
  (interactive)
  (matsugit--run (list "lint" (matsugit--source))))

(defun matsugit--repo-buffers (repo)
  "Return open file buffers in the real REPO, including symlink visits."
  (cl-remove-if-not
   (lambda (buffer)
     (with-current-buffer buffer
       (and buffer-file-name
            (file-in-directory-p (file-truename buffer-file-name) repo))))
   (buffer-list)))

(defun matsugit--sync-finished (repo buffer status)
  "Refresh unchanged REPO buffers after BUFFER reports successful STATUS."
  (when (string-match-p "\\`finished" status)
    (dolist (source (matsugit--repo-buffers repo))
      (with-current-buffer source
        (when (and (not (buffer-modified-p)) (file-exists-p buffer-file-name)
                   (not (verify-visited-file-modtime source)))
          (revert-buffer t t t))))
    (message "Git sync finished; unchanged buffers refreshed (see %s)" (buffer-name buffer))))

;;;###autoload
(defun matsugit-sync-from-git (check-only)
  "Pull upstream edits in the real source checkout, without pushing.
With prefix CHECK-ONLY, fetch/report without modifying working files.
Never stash, merge divergent histories, or overwrite unsaved buffers."
  (interactive "P")
  (unless (and buffer-file-name (not (file-remote-p buffer-file-name)))
    (user-error "Visit a local source file first"))
  (let* ((source (file-truename buffer-file-name))
         (repo (locate-dominating-file source ".git")))
    (unless repo (user-error "Source is not in a Git checkout"))
    (unless check-only
      (let ((dirty (cl-remove-if-not #'buffer-modified-p (matsugit--repo-buffers repo))))
        (when dirty
          (user-error "Unsaved buffers in this checkout: %s; save or reconcile first"
                      (mapconcat #'buffer-name dirty ", ")))))
    (when (or check-only (yes-or-no-p (format "Fast-forward %s from its upstream (no push)? " repo)))
      (let ((output (matsugit--run
                     (list "sync" source (if check-only "--check" "--yes")))))
        (unless check-only
          (with-current-buffer output
            (add-hook 'compilation-finish-functions
                      (apply-partially #'matsugit--sync-finished repo) nil t)))))))

;;;###autoload
(defun matsugit-publish (deploy)
  "Publish through the configured target after confirmation.
With prefix DEPLOY, also request its configured deployment. Source visibility
in rendered output remains governed by the document and renderer settings."
  (interactive "P")
  (let ((source (matsugit--source)))
    (when (yes-or-no-p
           (format "Commit/push document, slides and source%s to %s? "
                   (if deploy " and request configured deployment" "")
                   (or matsugit-target matsugit-target-repo "the configured/current repository")))
      (matsugit--run
       (append (list "publish" source "--yes")
               (when deploy '("--deploy"))
               (when matsugit-target (list "--target" matsugit-target))
               (if matsugit-target
                   (when matsugit-theme (list "--theme" matsugit-theme))
                 (matsugit--options)))))))

(provide 'matsugit)
;;; matsugit.el ends here
