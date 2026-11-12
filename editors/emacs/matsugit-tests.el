;;; matsugit-tests.el --- Standalone package contracts -*- lexical-binding: t; -*-

(require 'ert)
(require 'cl-lib)
(require 'matsugit)
(require 'matsugit-authoring)
(require 'matsugit-browser)
(require 'matsugit-tables)

(ert-deftest matsugit-package-load-is-opt-in-and-independent ()
  (should-not (featurep 'spacemacs))
  (should-not (fboundp 'mdf/matsugit-preview-slides))
  (should (equal matsugit-program "matsugit"))
  (should-not matsugit-theme-directories)
  (should-not matsugit-table-ssh-host)
  (dolist (hook '(org-mode-hook markdown-mode-hook gfm-mode-hook))
    (should-not (memq #'matsugit--enable-authoring (and (boundp hook) (symbol-value hook)))))
  (with-temp-buffer
    (should-not matsugit-mode)
    (should-not (key-binding (kbd "C-c m b")))))

(ert-deftest matsugit-package-mode-only-changes-local-completion ()
  (with-temp-buffer
    (setq buffer-file-name "/tmp/example.md")
    (insert "Draft\n")
    (let ((before (buffer-string)))
      (matsugit-mode 1)
      (should (eq (key-binding (kbd "C-c m b")) #'matsugit-open-browser))
      (should (memq #'matsugit-completion-at-point completion-at-point-functions))
      (with-temp-buffer (should-not matsugit-mode))
      (matsugit-mode -1)
      (should-not (memq #'matsugit-completion-at-point completion-at-point-functions))
      (should (equal before (buffer-string))))))

(ert-deftest matsugit-package-mode-refuses-wrong-buffer ()
  (with-temp-buffer
    (should-error (matsugit-mode 1) :type 'user-error)
    (should-not matsugit-mode)
    (should-not (memq #'matsugit-completion-at-point completion-at-point-functions))))

(ert-deftest matsugit-package-native-markdown-and-org-authoring ()
  (dolist (extension '("md" "org"))
    (with-temp-buffer
      (setq buffer-file-name (concat "/tmp/example." extension))
      (matsugit-mode 1)
      (matsugit-insert-slide "A clear claim")
      (should (string-prefix-p (if (equal extension "org") "** A clear claim" "## A clear claim") (buffer-string)))
      (goto-char (point-max))
      (matsugit-insert-notes)
      (should (string-match-p (if (equal extension "org") "#\\+begin_notes" "::: notes") (buffer-string))))))

(ert-deftest matsugit-package-new-deck-and-recipe-are-distinct ()
  (with-temp-buffer
    (setq buffer-file-name "/tmp/example.md")
    (matsugit-new-deck "New deck")
    (should (string-prefix-p "---\ntitle:" (buffer-string)))
    (let ((before (buffer-string)))
      (should-error (matsugit-new-deck "Again") :type 'user-error)
      (should (equal before (buffer-string))))
    (goto-char (point-max))
    (let (command)
      (cl-letf (((symbol-function 'call-process)
                 (lambda (&rest args) (setq command args) (insert "## A quote\n") 0)))
        (matsugit-insert-template "quotation"))
      (should (equal (nthcdr 4 command) '("template" "quotation" "--fragment" "--format" "markdown")))
      (should (string-suffix-p "## A quote\n" (buffer-string))))))

(ert-deftest matsugit-package-slash-ignores-literal-content ()
  (dolist (text '("```\n/slide" "---\ntitle: Draft\n/slide" "<!--\n/slide"))
    (with-temp-buffer
      (setq buffer-file-name "/tmp/example.md")
      (insert text)
      (should-not (matsugit-completion-at-point))))
  (with-temp-buffer
    (setq buffer-file-name "/tmp/example.md")
    (insert "/sl")
    (should (member "/slide" (nth 2 (matsugit-completion-at-point))))))

(ert-deftest matsugit-package-preview-delegates-to-cli-without-publishing ()
  (dolist (extension '("org" "md"))
    (let (arguments output)
      (cl-letf (((symbol-function 'matsugit--source) (lambda () (concat "/tmp/example." extension)))
                ((symbol-function 'make-temp-file) (lambda (&rest _) "/tmp/preview"))
                ((symbol-function 'matsugit--run) (lambda (args target) (setq arguments args output target))))
        (matsugit-preview-slides)
        (should (equal arguments (list "render" (concat "/tmp/example." extension) "--output" "/tmp/preview")))
        (should (equal output "/tmp/preview/slides.html"))))))

(ert-deftest matsugit-package-publish-needs-confirmation ()
  (cl-letf (((symbol-function 'matsugit--source) (lambda () "/tmp/example.md"))
            ((symbol-function 'yes-or-no-p) (lambda (&rest _) nil))
            ((symbol-function 'matsugit--run) (lambda (&rest _) (ert-fail "Published without confirmation"))))
    (matsugit-publish nil)))

(ert-deftest matsugit-package-browser-refuses-remote-and-nonlocal-results ()
  (with-temp-buffer
    (setq buffer-file-name "/ssh:example:/srv/deck.md")
    (cl-letf (((symbol-function 'matsugit--source) (lambda () (ert-fail "Saved remote source"))))
      (should-error (matsugit-open-browser) :type 'user-error)))
  (should (equal (matsugit--browser-address "{\"url\":\"http://127.0.0.1:1234/token/\"}") "http://127.0.0.1:1234/token/"))
  (should-error (matsugit--browser-address "{\"url\":\"https://example.com/\"}")))

(ert-deftest matsugit-package-tables-preserve-concurrent-edits ()
  (with-temp-buffer
    (insert "| Name | Value |\n| --- | --- |\n| A | 1 |\n")
    (let ((before (buffer-string)) (start (copy-marker (point-min))) (end (copy-marker (point-max))))
      (goto-char (point-min))
      (insert "Changed")
      (let ((changed (buffer-string)))
        (should-error (matsugit-table--apply (current-buffer) start end before "Replacement") :type 'user-error)
        (should (equal changed (buffer-string)))))))

(ert-deftest matsugit-package-themes-are-explicit ()
  (let ((root (make-temp-file "matsugit-themes-" t)))
    (unwind-protect
        (progn
          (make-directory (expand-file-name "example" root))
          (with-temp-file (expand-file-name "example/theme.json" root) (insert "{}"))
          (let ((matsugit-theme-directories (list root root)))
            (should (equal (matsugit--themes) '("default" "example")))))
      (delete-directory root t))))

;;; matsugit-tests.el ends here
