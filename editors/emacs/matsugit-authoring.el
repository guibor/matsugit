;;; matsugit-authoring.el --- Matsugit document authoring -*- lexical-binding: t; -*-

;; Copyright (c) 2026 MDF (guibor)
;; SPDX-License-Identifier: MIT

;;; Commentary:
;; Part of the matsugit Emacs package. See README.org in this directory.

;;; Code:

(require 'cl-lib)
(require 'json)
(require 'subr-x)
(require 'matsugit)
(require 'matsugit-comments)

(defun matsugit-insert--org-p ()
  "Whether the current source uses Org syntax."
  (or (derived-mode-p 'org-mode)
      (equal (downcase (or (file-name-extension (or buffer-file-name "")) "")) "org")))

(defun matsugit-insert--heading (level title)
  "Return a source heading at LEVEL with TITLE."
  (concat (make-string level (if (matsugit-insert--org-p) ?* ?#)) " "
          (matsugit-insert--title title) "\n\n"))

(defun matsugit-insert--wrap (name placeholder &optional markdown-attrs org-attrs)
  "Wrap the region in NAME using native syntax, or insert PLACEHOLDER."
  (matsugit-insert--insert-block
   (if (matsugit-insert--org-p) (concat "#+begin_" name org-attrs "\n")
     (concat "::: " (or markdown-attrs name) "\n"))
   (if (matsugit-insert--org-p) (concat "\n#+end_" name "\n") "\n:::\n")
   placeholder t))

(defun matsugit-insert--check-buffer ()
  "Require editable Org or Markdown, without switching major modes."
  (barf-if-buffer-read-only)
  (unless (or (derived-mode-p 'org-mode 'markdown-mode 'gfm-mode 'markdown-modern-mode
                             'markdown-ts-mode 'md-mode 'md-ts-mode 'quarto-mode)
              (member (downcase (or (file-name-extension (or buffer-file-name "")) ""))
                      '("md" "markdown" "qmd" "org")))
    (user-error "Slide insertion requires an editable Org or Markdown buffer")))

(defun matsugit-insert--title (title)
  "Validate a single-line TITLE without changing its punctuation or Unicode."
  (when (or (string-empty-p (string-trim title)) (string-match-p "[\r\n]" title))
    (user-error "Use a non-empty, single-line title"))
  (string-trim title))

(defun matsugit-insert--insert-block (before after placeholder &optional select)
  "Insert BEFORE, region or PLACEHOLDER, and AFTER as a Markdown block.
Keep surrounding text, ensure blank-line boundaries, and optionally SELECT the
inserted content.  The whole insertion is one undoable change."
  (matsugit-insert--check-buffer)
  (let* ((region (use-region-p))
         (start (if region (region-beginning) (point)))
         (end (if region (region-end) start))
         (body (if region (buffer-substring-no-properties start end) placeholder)))
    (atomic-change-group
      (goto-char start)
      (when region (delete-region start end))
      (unless (bolp) (insert "\n"))
      (unless (or (bobp) (save-excursion (forward-line -1) (looking-at-p "[ \t]*$")))
        (insert "\n"))
      (insert before)
      (let ((body-start (point)))
        (insert body)
        (let ((body-end (point)))
          (insert after)
          (unless (bolp) (insert "\n"))
          (unless (looking-at-p "[ \t]*$") (insert "\n"))
          (when (eobp) (insert "\n"))
          (goto-char body-start)
          (deactivate-mark)
          (when (and select (> body-end body-start))
            (push-mark body-end t t)
            (setq deactivate-mark nil)))))))

;;;###autoload
(defun matsugit-insert-slide (title)
  "Insert an H2 slide TITLE, preserving any selected text as its body."
  (interactive "sSlide title: ")
  (matsugit-insert--insert-block (matsugit-insert--heading 2 title) "" ""))

;;;###autoload
(defun matsugit-insert-section (title)
  "Insert an H1 section TITLE; YAML decides whether it gets a divider slide."
  (interactive "sSection title: ")
  (matsugit-insert--insert-block (matsugit-insert--heading 1 title) "" ""))

;;;###autoload
(defun matsugit-insert-subtitle (title)
  "Insert an H3 subtitle TITLE directly after an H2 or manual slide break."
  (interactive "sSubtitle / main claim: ")
  (matsugit-insert--insert-block (matsugit-insert--heading 3 title) "" ""))

;;;###autoload
(defun matsugit-insert-division (title)
  "Insert an H4 content division TITLE within the current slide."
  (interactive "sContent division title: ")
  (if (matsugit-insert--org-p)
      (matsugit-insert--wrap "region" "Supporting point."
                        nil (concat " :title " (json-encode-string (matsugit-insert--title title))))
    (matsugit-insert--insert-block (matsugit-insert--heading 4 title) "" "")))

;;;###autoload
(defun matsugit-insert-takeaway ()
  "Wrap the region in a takeaway, or insert and select a short placeholder."
  (interactive)
  (matsugit-insert--wrap "takeaway" "Key takeaway."))

;;;###autoload
(defun matsugit-insert-columns (count &optional untitled ratio)
  "Insert COUNT columns, two or three, optionally UNTITLED with RATIO.
The default is equal width. The region becomes the first column; otherwise
select its placeholder."
  (interactive
   (let* ((choice (completing-read "Columns: "
                                  '("2 with titles" "2 evidence + commentary" "3 with titles" "2 untitled" "3 untitled")
                                  nil t nil nil "2 with titles")))
     (list (string-to-number choice) (string-suffix-p "untitled" choice)
           (when (string-match-p "evidence" choice) "2:1"))))
  (matsugit-insert--insert-regions count untitled "columns" "column" "Column" ratio))

(defun matsugit-insert--insert-regions (count untitled group item label &optional ratio)
  "Insert COUNT regions in GROUP with ITEM blocks or LABEL headings."
  (unless (memq count '(2 3)) (user-error "Use two or three %s" group))
  (when (and ratio (not (member ratio (if (= count 2) '("1:1" "2:1" "1:2") '("1:1:1")))))
    (user-error "Ratio must match the number of columns"))
  (let* ((org (matsugit-insert--org-p))
         (heading (lambda (n)
                    (cond (org (format "#+begin_%s%s\n\n" item
                                       (if untitled "" (format " :title \"%s %d\"" label n))))
                          (untitled (format "::: %s\n\n" item))
                          (t (format "#### %s %d\n\n" label n)))))
         (end (cond (org (format "\n\n#+end_%s\n" item))
                    (untitled "\n\n:::\n") (t "\n")))
         (after end))
    (dotimes (index (1- count))
      (setq after (concat after "\n" (funcall heading (+ index 2)) "- Supporting point." end)))
    (matsugit-insert--insert-block (concat (if org "#+begin_" ":::: ") group
                                    (if ratio (if org (format " :ratio \"%s\"" ratio) (concat " " ratio)) "")
                                    "\n\n" (funcall heading 1))
                             (concat after (if org (format "\n#+end_%s\n" group) "\n::::\n"))
                             "- Supporting point." t)))

;;;###autoload
(defun matsugit-insert-rows (count &optional untitled)
  "Insert COUNT stacked sections for matsugit, optionally UNTITLED.
The region becomes the first section. Sections are content-sized, not cropped
to a fixed half-height. Requires `slide-layout: structured' or `title-claim'."
  (interactive
   (let ((choice (completing-read "Stacked sections: "
                                 '("2 untitled" "2 with titles" "3 untitled" "3 with titles")
                                 nil t nil nil "2 untitled")))
     (list (string-to-number choice) (string-suffix-p "untitled" choice))))
  (matsugit-insert--insert-regions count untitled "rows" "row" "Section"))

;;;###autoload
(defun matsugit-insert-break ()
  "Insert a manual continuation-slide break for `slide-layout: structured'.
It remains a horizontal rule in the reading document.  Selected text is
preserved after the break; code fences and YAML are not slide breaks."
  (interactive)
  (matsugit-insert--check-buffer)
  (when (= (if (use-region-p) (region-beginning) (point)) (point-min))
    (user-error "Insert a slide break after content, not at the start of a document"))
  (matsugit-insert--insert-block (if (matsugit-insert--org-p) "-----\n\n" "---\n\n") "" ""))

;;;###autoload
(defun matsugit-insert-notes ()
  "Wrap the region in presenter notes, or insert a notes placeholder."
  (interactive)
  (matsugit-insert--wrap "notes" "Presenter notes."))

;;;###autoload
(defun matsugit-insert-document-only ()
  "Wrap the region as reading-document content excluded from slides."
  (interactive)
  (matsugit-insert--wrap "content-visible" "Supporting detail for the reading document."
                    "{.content-visible unless-format=\"revealjs\"}" " :unless-format \"revealjs\""))

;;;###autoload
(defun matsugit-new-deck (title)
  "Create a structured deck template with TITLE in an otherwise empty buffer.
Never overwrite existing metadata or silently migrate an existing document."
  (interactive "sDeck title: ")
  (matsugit-insert--check-buffer)
  (matsugit-insert--title title)
  (save-restriction
    (widen)
    (unless (string-empty-p (string-trim (buffer-string)))
      (user-error "Deck template requires an empty buffer; existing content was not changed"))
    (atomic-change-group
      (erase-buffer) ; Whitespace before the YAML would stop it being front matter.
      (if (matsugit-insert--org-p)
          (matsugit-insert--insert-block
           (concat "#+TITLE: " (string-trim title)
                   "\n#+SLIDE_LAYOUT: structured\n#+SLIDE_SECTION_DIVIDERS: false\n\n* Section\n\n** ")
           "\n\n*** Main claim\n\n- Supporting point.\n\n#+begin_takeaway\nKey takeaway.\n#+end_takeaway\n"
           "Slide title" t)
        (matsugit-insert--insert-block
         (concat "---\ntitle: " (json-encode-string (string-trim title))
                 "\nslide-layout: structured\nslide-section-dividers: false\n---\n\n# Section\n\n## ")
         "\n\n### Main claim\n\n- Supporting point.\n\n::: takeaway\nKey takeaway.\n:::\n"
         "Slide title" t)))))

;;;###autoload
(defun matsugit-insert-help ()
  "Open the slide taxonomy and authoring reference."
  (interactive)
  (browse-url "https://github.com/guibor/matsugit/blob/main/skills/matsugit/references/authoring.md"))

(defconst matsugit-insert--insert-actions
  '(("Slide (H2)" . matsugit-insert-slide)
    ("Subtitle / claim (H3)" . matsugit-insert-subtitle)
    ("Section (H1)" . matsugit-insert-section)
    ("Division (H4)" . matsugit-insert-division)
    ("Takeaway" . matsugit-insert-takeaway)
    ("Takeaway (short form)" . matsugit-insert-takeaway-callout)
    ("Columns" . matsugit-insert-columns)
    ("Columns (evidence + commentary)" . matsugit-insert-evidence-columns)
    ("Chart from selected table" . matsugit-insert-chart)
    ("Source attribution" . matsugit-insert-source)
    ("Slash command menu" . matsugit-slash-menu)
    ("Rows / stacked sections (matsugit)" . matsugit-insert-rows)
    ("Manual slide break" . matsugit-insert-break)
    ("Presenter notes" . matsugit-insert-notes)
    ("Document-only detail" . matsugit-insert-document-only)
    ("Agent comment (hidden)" . matsugit-insert-agent-comment)
    ("Delete agent comment at point" . matsugit-delete-agent-comment)
    ("Complete slide recipe" . matsugit-insert-template)
    ("Taxonomy / help" . matsugit-insert-help)
    ("New deck template" . matsugit-new-deck)))

;;;###autoload
(defun matsugit-insert-menu ()
  "Choose an Org or Markdown slide block; never render or publish anything."
  (interactive)
  (matsugit-insert--check-buffer)
  (call-interactively
   (cdr (assoc (completing-read "Insert slide block: " matsugit-insert--insert-actions nil t)
               matsugit-insert--insert-actions))))

(defun matsugit-insert-takeaway-callout ()
  "Wrap selected text as a takeaway, using native syntax for the buffer."
  (interactive)
  (matsugit-insert--check-buffer)
  (if (matsugit-insert--org-p)
      (matsugit-insert-takeaway)
    (let* ((region (use-region-p))
           (start (if region (region-beginning) (point)))
           (end (if region (region-end) start))
           (body (if region (buffer-substring-no-properties start end) "Key takeaway.")))
      (atomic-change-group
        (delete-region start end)
        (goto-char start)
        (deactivate-mark)
        (matsugit-insert--insert-block "> [!TAKEAWAY]\n" "\n"
                                 (mapconcat (lambda (line) (concat "> " line))
                                            (split-string body "\n" nil) "\n") t)))))

(defun matsugit-insert-evidence-columns ()
  "Insert two columns in a 2:1 ratio; preserve the selected evidence."
  (interactive)
  (matsugit-insert-columns 2 nil "2:1"))

(defun matsugit-insert-three-columns ()
  "Insert three equal columns, preserving selected text in the first."
  (interactive)
  (matsugit-insert-columns 3))

(defun matsugit-insert-source ()
  "Wrap selected text as a source attribution, or insert a placeholder."
  (interactive)
  (matsugit-insert--wrap "source" "Source, date, page or link."))

(defun matsugit-insert-table ()
  "Insert a small native table without opening a separate editor."
  (interactive)
  (matsugit-insert--insert-block "" "\n"
                           (concat "| Measure | Value |\n"
                                   (if (matsugit-insert--org-p) "|---------+-------|\n" "| :--- | ---: |\n")
                                   "| Example | 0 |") t))

(defun matsugit-insert-chart (type unit)
  "Wrap the selected pipe table as a chart, or insert a small editable table."
  (interactive (list (completing-read "Chart: " '("barh" "bar" "line" "stacked" "stacked100") nil t)
                     (read-string "Unit: " "units")))
  (matsugit-insert--check-buffer)
  (unless (member type '("barh" "bar" "line" "stacked" "stacked100"))
    (user-error "Unsupported chart type"))
  (when (or (string-empty-p (string-trim unit)) (string-match-p "[\"\r\n]" unit))
    (user-error "Use a non-empty single-line unit without quotation marks"))
  (when (use-region-p)
    (let ((body (string-trim (buffer-substring-no-properties (region-beginning) (region-end)))))
      (unless (and (not (string-empty-p body))
                   (cl-every (lambda (line) (string-match-p "\\`[ \t]*|.*|[ \t]*\\'" line))
                             (split-string body "\n" nil)))
        (user-error "Select one pipe table; no text was changed"))))
  (let ((org (matsugit-insert--org-p)))
    (matsugit-insert--insert-block
     (if org (format "#+begin_chart :type %S :unit %S\n" type unit)
       (format "::: {.chart type=%S unit=%S}\n" type unit))
     (if org "\n#+end_chart\n" "\n:::\n")
     (concat "| Experience | Value |\n"
             (if org "|------------+-------|\n" "| :--- | ---: |\n")
             "| Baseline | 12 |\n| Pilot | 8 |") t)))

(defun matsugit-insert-canvas ()
  "Insert a local HTML canvas in the buffer's native Org or Markdown syntax."
  (interactive)
  (matsugit-insert-template "canvas"))

(defconst matsugit--slash-actions
  '(("slide" . matsugit-insert-slide)
    ("claim" . matsugit-insert-subtitle)
    ("section" . matsugit-insert-section)
    ("region" . matsugit-insert-division)
    ("columns" . matsugit-insert-columns)
    ("columns-evidence" . matsugit-insert-evidence-columns)
    ("columns-3" . matsugit-insert-three-columns)
    ("rows" . matsugit-insert-rows)
    ("chart" . matsugit-insert-chart)
    ("canvas" . matsugit-insert-canvas)
    ("takeaway" . matsugit-insert-takeaway-callout)
    ("notes" . matsugit-insert-notes)
    ("source" . matsugit-insert-source)
    ("table" . matsugit-insert-table)
    ("document-only" . matsugit-insert-document-only)
    ("break" . matsugit-insert-break)
    ("agent-comment" . matsugit-insert-agent-comment)
    ("cover" . matsugit-insert-cover-slide)
    ("statement" . matsugit-insert-statement-slide)
    ("summary" . matsugit-insert-summary-slide)
    ("okr-summary" . matsugit-insert-okr-summary-slide)
    ("okr-objective" . matsugit-insert-okr-objective-slide)
    ("process" . matsugit-insert-process-slide)
    ("d2" . matsugit-insert-d2-slide)
    ("quote" . matsugit-insert-quotation-slide)
    ("quotation" . matsugit-insert-quotation-slide)
    ("comparison" . matsugit-insert-comparison-slide)
    ("metrics" . matsugit-insert-metrics-slide)
    ("timeline" . matsugit-insert-timeline-slide)
    ("decision" . matsugit-insert-decision-slide)
    ("implication" . matsugit-insert-implication-slide)
    ("mapping" . matsugit-insert-mapping-slide)
    ("annotated" . matsugit-insert-annotated-slide)))

(defun matsugit--literal-p (position)
  "Whether POSITION is in code, metadata, HTML or an agent review block.
Scan only for explicit literal delimiters; never fontify a large buffer."
  (save-excursion
    (goto-char (point-min))
    (let ((org (matsugit-insert--org-p)) code html review yaml)
      (setq yaml (and (not org) (looking-at-p "---[ \t]*$")))
      (when yaml (forward-line 1))
      (while (< (point) position)
        (let ((line (buffer-substring-no-properties (line-beginning-position) (line-end-position))))
          (cond
           (yaml (when (string-match-p "\\`\\(?:---\\|\\.\\.\\.\\)[ \t]*\\'" line) (setq yaml nil)))
           (org
            (cond (code (when (string-match-p (concat "^[ \t]*#\\+end_" (regexp-quote code) "[ \t]*$") (downcase line)) (setq code nil)))
                  ((string-match "^[ \t]*#\\+begin_\\(src\\|example\\|export\\|comment\\|agent-comment\\)\\b" (downcase line))
                   (setq code (match-string 1 (downcase line))))))
           (html (when (string-match-p html line) (setq html nil)))
           (code (when (string-match-p (concat "^ \\{0,3\\}" (regexp-quote (substring code 0 1)) "\\{" (number-to-string (length code)) ",\\}[ \t]*$") line) (setq code nil)))
           ((string-match "^ \\{0,3\\}\\(`\\{3,\\}\\|~\\{3,\\}\\)" line) (setq code (match-string 1 line)))
           ((string-match "^ \\{0,3\\}<!--" line) (unless (string-match-p "-->" line) (setq html "-->")))
           ((string-match "^ \\{0,3\\}<\\([[:alpha:]][[:alnum:]-]*\\)\\b" line)
            (let* ((tag (match-string 1 line))
                   (closing (concat "</" tag "[ \t]*>"
                                    (unless (member (downcase tag) '("script" "style" "pre" "textarea"))
                                      "\\|^[ \t]*$"))))
              (unless (string-match-p closing line) (setq html closing))))
           ((and (null review) (string-match "^ \\{0,3\\}\\(:\\{3,\\}\\).*agent-comment\\b" line))
            (setq review (length (match-string 1 line))))
           ((and review (string-match-p (format "^ \\{0,3\\}:\\{%d,\\}[ \t]*$" review) line)) (setq review nil))))
        (forward-line 1))
      (or code html review yaml))))

(defun matsugit--slash-bounds ()
  "Return a standalone slash prefix before point, outside literal content."
  (when (and (not buffer-read-only)
             (save-excursion
               (beginning-of-line)
               (looking-at " \\{0,3\\}\\(/[-a-z0-9]*\\)"))
             (= (match-end 1) (point))
             (looking-at-p "[ \t]*$")
             (or (= (line-beginning-position) (point-min))
                 (save-excursion (forward-line -1) (looking-at-p "[ \t]*$"))))
    (let ((start (match-beginning 1)) (end (point)))
      (unless (matsugit--literal-p (line-beginning-position)) (cons start end)))))

(defun matsugit--run-slash (name)
  "Run the local insertion helper NAME, loading recipe helpers only on demand."
  (let ((command (cdr (assoc name matsugit--slash-actions))))
    (unless command (user-error "Unknown slide command: %s" name))
    (unless (fboundp command)
      (require 'matsugit))
    (call-interactively command)))

(defun matsugit-completion-at-point ()
  "Complete standalone /slide commands without rebinding ordinary typing."
  (when-let* ((bounds (matsugit--slash-bounds)))
    (let ((start (copy-marker (car bounds))) (buffer (current-buffer)))
      (list (car bounds) (cdr bounds)
            (mapcar (lambda (entry) (concat "/" (car entry))) matsugit--slash-actions)
            :exclusive 'no
            :annotation-function (lambda (_) "  slide element")
            :exit-function
            (lambda (candidate status)
              (when (and (memq status '(finished exact)) (buffer-live-p buffer))
                (with-current-buffer buffer
                  (atomic-change-group
                    (delete-region start (+ start (length candidate)))
                    (goto-char start)
                    (matsugit--run-slash (substring candidate 1))))))))))

(defun matsugit-slash-menu ()
  "Insert an element, or wrap selected text/table. No export or publication."
  (interactive)
  (matsugit-insert--check-buffer)
  (let* ((bounds (matsugit--slash-bounds))
         (initial (when bounds (buffer-substring-no-properties (1+ (car bounds)) (cdr bounds))))
         (name (completing-read "Insert /" matsugit--slash-actions nil t initial)))
    (atomic-change-group
      (when bounds
        (delete-region (car bounds) (cdr bounds))
        (goto-char (car bounds)))
      (matsugit--run-slash name))))

(defalias 'matsugit-insert #'matsugit-slash-menu)

(defun matsugit--complete-inserted-slash ()
  "Offer completion after typing a standalone slash, never inside literal text."
  (when (and (eq last-command-event ?/) (matsugit--slash-bounds))
    (completion-at-point)))

(defvar matsugit-authoring-mode-map
  (let ((map (make-sparse-keymap)))
    (dolist (key '("TAB" "<tab>"))
      (define-key map (kbd key)
        '(menu-item "" nil :filter
                    (lambda (_) (when (matsugit--slash-bounds) #'completion-at-point)))))
    map))

(define-key matsugit-authoring-mode-map (kbd "C-c C-/") #'matsugit-insert)
(dolist (binding '(("b" . matsugit-open-browser) ("s" . matsugit-story)
                   ("d" . matsugit-preview-document) ("p" . matsugit-preview-slides)
                   ("i" . matsugit-insert) ("t" . matsugit-edit-table)
                   ("e" . matsugit-export) ("P" . matsugit-publish)))
  (define-key matsugit-authoring-mode-map (kbd (concat "C-c m " (car binding))) (cdr binding)))

(defvaralias 'matsugit-mode 'matsugit-authoring-mode)

(define-minor-mode matsugit-authoring-mode
  "Contextual slash completion in editable Markdown and Org sources."
  :lighter nil :keymap matsugit-authoring-mode-map
  (when matsugit-authoring-mode
    (condition-case err
        (matsugit-insert--check-buffer)
      (error (setq matsugit-authoring-mode nil) (signal (car err) (cdr err)))))
  (if matsugit-authoring-mode
      (progn
        (add-hook 'completion-at-point-functions #'matsugit-completion-at-point nil t)
        (add-hook 'post-self-insert-hook #'matsugit--complete-inserted-slash nil t))
    (remove-hook 'completion-at-point-functions #'matsugit-completion-at-point t)
    (remove-hook 'post-self-insert-hook #'matsugit--complete-inserted-slash t)))

;;;###autoload
(defalias 'matsugit-mode #'matsugit-authoring-mode)

(defun matsugit--enable-authoring ()
  (unless buffer-read-only (matsugit-authoring-mode 1)))

(provide 'matsugit-authoring)
;;; matsugit-authoring.el ends here
