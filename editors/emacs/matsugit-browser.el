;;; matsugit-browser.el --- Matsugit document authoring -*- lexical-binding: t; -*-

;; Copyright (c) 2026 MDF (guibor)
;; SPDX-License-Identifier: MIT

;;; Commentary:
;; Part of the matsugit Emacs package. See README.org in this directory.

;;; Code:

(require 'json)
(require 'subr-x)
(require 'browse-url)
(require 'matsugit)

(defvar-local matsugit--browser-process nil
  "Pending browser workspace launcher for this source buffer.")

(defun matsugit--browser-address (text)
  "Read a local workspace address from the launcher's JSON TEXT."
  (let* ((data (json-parse-string text :object-type 'alist))
         (url (alist-get 'url data)))
    (unless (and (stringp url)
                 (string-match-p
                  "\\`http://127\\.0\\.0\\.1:[0-9]+/[A-Za-z0-9_-]+/\\'" url))
      (error "The launcher did not return a local workspace address"))
    url))

;;;###autoload
(defun matsugit-open-browser ()
  "Save this source and open the editable matsugit workspace in a browser.
Uses the same file, not an exported copy.  No publication or Git operation.
The server binds only to localhost; TRAMP files require opening on their host."
  (interactive)
  (when (file-remote-p (or buffer-file-name default-directory))
    (user-error "Open the browser workspace on the file's host; TRAMP needs a private tunnel.  Static previews remain available"))
  (when (and matsugit--browser-process
             (process-live-p matsugit--browser-process))
    (user-error "The browser workspace is still starting"))
  (let* ((source (matsugit--source))
         (default-directory (file-name-directory source))
         (output (generate-new-buffer "*matsugit browser*"))
         (errors (generate-new-buffer "*matsugit browser errors*"))
         finished)
    (condition-case err
        (setq matsugit--browser-process
              (make-process
               :name "matsugit-browser-open" :buffer output :stderr errors
               :connection-type 'pipe :noquery t
               :command (list matsugit-program "open" source "--no-browser" "--json")
               :sentinel
               (lambda (process _event)
                 (when (and (not finished) (memq (process-status process) '(exit signal)))
                   (setq finished t)
                   (condition-case err
                       (progn
                         (unless (zerop (process-exit-status process))
                           (error "Matsugit launcher failed; see the diagnostic buffer"))
                         (let ((url (with-current-buffer output
                                      (matsugit--browser-address (buffer-string)))))
                           (browse-url url)
                           (message "matsugit browser workspace opened for %s" (file-name-nondirectory source)))
                         (kill-buffer output)
                         (kill-buffer errors))
                     (error
                      (display-buffer (if (and (buffer-live-p errors)
                                               (> (buffer-size errors) 0)) errors output))
                      (message "matsugit: %s" (error-message-string err))))))))
      (error
       (kill-buffer output)
       (kill-buffer errors)
       (user-error "Cannot start matsugit: %s" (error-message-string err)))))
  (message "Opening matsugit in your browser..."))

(provide 'matsugit-browser)
;;; matsugit-browser.el ends here
