;;; matsugit-comments.el --- Matsugit document authoring -*- lexical-binding: t; -*-

;; Copyright (c) 2026 MDF (guibor)
;; SPDX-License-Identifier: MIT

;;; Commentary:
;; Part of the matsugit Emacs package. See README.org in this directory.

;;; Code:

(require 'cl-lib)
(require 'subr-x)
(declare-function org-element-property "org-element" (property element))
(declare-function org-element-context "org-element" (&optional element))
(declare-function org-element-lineage "org-element" (datum &optional types with-self))
(declare-function matsugit-insert--check-buffer "matsugit-authoring")
(declare-function matsugit-insert--org-p "matsugit-authoring")
(declare-function matsugit-insert--insert-block "matsugit-authoring")
(defun matsugit--markdown-agent-comments ()
  "Find balanced agent-comment blocks, ignoring literal code fences."
  (save-excursion
    (goto-char (point-min))
    (let (code stack found)
      (while (not (eobp))
        (let ((start (point))
              (line (buffer-substring-no-properties (line-beginning-position) (line-end-position))))
          (cond
           ((string-match "\\` \\{0,3\\}\\(`\\{3,\\}\\|~\\{3,\\}\\)\\(.*\\)\\'" line)
            (let ((fence (match-string 1 line)) (tail (string-trim (match-string 2 line))))
              (if code
                  (when (and (= (aref fence 0) (car code)) (>= (length fence) (cdr code))
                             (string-empty-p tail))
                    (setq code nil))
                (setq code (cons (aref fence 0) (length fence))))))
           ((and (not code) (string-match "\\` \\{0,3\\}\\(:\\{3,\\}\\)[ \t]*\\(.*\\)\\'" line))
            (let ((length (length (match-string 1 line))) (info (match-string 2 line)))
              (if (string-empty-p info)
                  (when (and stack (>= length (caar stack)))
                    (let ((entry (pop stack)))
                      (when (nth 2 entry)
                        (push (cons (nth 1 entry) (min (point-max) (1+ (line-end-position)))) found))))
                (push (list length start (string-match-p "\\(?:\\`\\|[.{ \t]\\)agent-comment\\(?:[ }\t]\\|\\'\\)" info)) stack)))))
          (forward-line 1)))
      (nreverse found))))

(defun matsugit--agent-comment-bounds ()
  "Return the complete comment at point, never another slide's comment."
  (if (matsugit-insert--org-p)
      (progn
        (require 'org-element)
        (let ((element (org-element-lineage (org-element-context) '(special-block) t)))
          (when (and element (equal (downcase (org-element-property :type element)) "agent-comment"))
            (cons (org-element-property :post-affiliated element)
                  (save-excursion
                    (goto-char (org-element-property :end element))
                    (skip-chars-backward " \t\n")
                    (min (point-max) (1+ (line-end-position))))))))
    (cl-find-if (lambda (bounds) (and (<= (car bounds) (point)) (< (point) (cdr bounds))))
                (matsugit--markdown-agent-comments))))

;;;###autoload
(defun matsugit-insert-agent-comment ()
  "Insert a hidden per-slide request and response block; wrap selected text.
The renderer excludes this block from derived/published outputs. Its local
source remains readable by agents; never put secrets in collaboration notes."
  (interactive)
  (require 'matsugit-authoring)
  (matsugit-insert--check-buffer)
  (when (matsugit--agent-comment-bounds)
    (user-error "Edit the existing comment; do not nest agent comments"))
  (let* ((org (matsugit-insert--org-p))
         (body (if (use-region-p) (buffer-substring-no-properties (region-beginning) (region-end)) ""))
         (id (concat "review-" (substring (md5 (format "%S:%s:%s" (current-time) (random) (buffer-name))) 0 12))))
    (when (and org (let ((case-fold-search t)) (string-match-p "^[ \t]*#\\+end_agent-comment" body)))
      (user-error "The selected text contains an agent-comment closing delimiter"))
    (let ((fence "::::"))
      (unless org
        (let ((start 0) (width 3))
          (while (string-match "^ \\{0,3\\}\\(:\\{3,\\}\\)" body start)
            (setq width (max width (length (match-string 1 body))) start (match-end 0)))
          (setq fence (make-string (1+ width) ?:))))
      (matsugit-insert--insert-block
       (if org (format "#+begin_agent-comment :id \"%s\" :status \"open\"\nRequest:\n" id)
         (format "%s {.agent-comment #%s status=\"open\"}\nRequest:\n" fence id))
       (concat "\n\nResponse:\nPending.\n" (if org "#+end_agent-comment" fence) "\n")
       "Describe the change or question for this slide." t))))

;;;###autoload
(defun matsugit-delete-agent-comment ()
  "Delete only the agent comment at point, as one undoable edit."
  (interactive)
  (require 'matsugit-authoring)
  (matsugit-insert--check-buffer)
  (let ((bounds (matsugit--agent-comment-bounds)))
    (unless bounds (user-error "Put point inside the agent comment to delete"))
    (when (or (not (called-interactively-p 'interactive))
              (yes-or-no-p "Delete this agent comment and its response? "))
      (undo-boundary)
      (atomic-change-group (delete-region (car bounds) (cdr bounds)))
      (undo-boundary))))

(provide 'matsugit-comments)
;;; matsugit-comments.el ends here
