"""Links to a shared deck and the progress of its site build."""
import unittest

from matsugit.links import build_step, links


class LinkTests(unittest.TestCase):
    def receipt(self, **changes):
        value = {'provider': 'gitlab', 'project_url': 'https://git.example.invalid/team/docs', 'branch': 'main',
                 'source_path': 'matsugit-site/deck/source.md', 'site_url': 'https://team.example.invalid/docs/',
                 'ci_layout': 'native', 'site_dir': 'matsugit-site'}
        value.update(changes)
        return value

    def test_native_site_gives_slides_document_and_source(self):
        self.assertEqual(links(self.receipt()), {
            'project': 'https://git.example.invalid/team/docs',
            'source': 'https://git.example.invalid/team/docs/-/blob/main/matsugit-site/deck/source.md',
            'edit': 'https://git.example.invalid/team/docs/-/edit/main/matsugit-site/deck/source.md',
            'site': 'https://team.example.invalid/docs/',
            'document': 'https://team.example.invalid/docs/deck/index.html',
            'slides': 'https://team.example.invalid/docs/deck/slides.html'})

    def test_github_paths_spaces_and_a_missing_site(self):
        result = links(self.receipt(provider='github', project_url='https://github.com/team/docs', site_url=None,
                                    source_path='matsugit-site/my deck/source.org'))
        self.assertEqual(result['source'], 'https://github.com/team/docs/blob/main/matsugit-site/my%20deck/source.org')
        self.assertNotIn('slides', result)
        self.assertNotIn('document', result)

    def test_topics_matches_emacs_pages_paths_and_can_be_overridden(self):
        topics = self.receipt(ci_layout='topics', source_path='topics/matsugit/deck/source.md')
        self.assertEqual(links(topics)['slides'], 'https://team.example.invalid/docs/topics/matsugit/deck/source-slides.html')
        self.assertEqual(links(topics)['document'], 'https://team.example.invalid/docs/topics/matsugit/deck/source.html')
        org = links({**topics, 'source_path': 'guides/a deck/road #1.org'})
        self.assertEqual(org['slides'], 'https://team.example.invalid/docs/guides/a%20deck/road%20%231-slides.html')
        self.assertNotIn('slides', links({**topics, 'ci_layout': 'unknown'}))
        configured = links({**topics, 'slides_url': '{site}/{slug}/slides.html', 'document_url': '{site}/{dir}/'})
        self.assertEqual(configured['slides'], 'https://team.example.invalid/docs/deck/slides.html')
        self.assertEqual(configured['document'], 'https://team.example.invalid/docs/topics/matsugit/deck/')
        self.assertNotIn('slides', links({**topics, 'slides_url': '{unknown}/x'}))

    def test_plain_http_sites_are_navigation_only_not_provider_endpoints(self):
        result = links(self.receipt(site_url='http://team.example.invalid/docs', project_url='http://git.example.invalid/team/docs'))
        self.assertEqual(result['slides'], 'http://team.example.invalid/docs/deck/slides.html')
        self.assertNotIn('source', result)
        self.assertNotIn('project', result)
        for bad in ('https://user:secret@team.example.invalid', 'http://user@team.example.invalid', 'javascript:alert(1)',
                    'https://[broken', 'https://team.example.invalid/a b', 'https://team.example.invalid/\n', 42):
            self.assertNotIn('site', links(self.receipt(site_url=bad)))
        self.assertEqual(links({}), {})

    def test_url_components_are_encoded_without_changing_path_separators(self):
        receipt = self.receipt(source_path='matsugit-site/Road #1?/source.md', branch='review/new deck')
        result = links(receipt)
        self.assertEqual(result['slides'], 'https://team.example.invalid/docs/Road%20%231%3F/slides.html')
        self.assertIn('/blob/review%2Fnew%20deck/matsugit-site/Road%20%231%3F/source.md', result['source'])
        result = links({**receipt, 'ci_layout': 'topics', 'slides_url': '{site}/{slug}/{name}.html',
                        'document_url': '{site}/{dir}/index.html'})
        self.assertEqual(result['slides'], 'https://team.example.invalid/docs/Road%20%231%3F/source.html')
        self.assertEqual(result['document'], 'https://team.example.invalid/docs/matsugit-site/Road%20%231%3F/index.html')
        self.assertNotIn('slides', links({**receipt, 'slides_url': 42}))

    def test_build_progress_is_read_from_the_log(self):
        self.assertIsNone(build_step('Preparing environment\nsetup done\n'))
        self.assertEqual(build_step('Rendering html: index.html\n'), 'document')
        self.assertEqual(build_step('Rendering html: index.html\nRendering revealjs: slides.html\n'), 'slides')
        self.assertEqual(build_step('Output created: index.html\nOutput created: slides.html\n'), 'slides')
        self.assertEqual(build_step('Rendering revealjs: slides.html\nUploading artifacts...\n'), 'publishing')


if __name__ == '__main__':
    unittest.main()
