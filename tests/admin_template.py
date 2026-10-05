"""Prevent admin controls from escaping the Vue page into script blocks."""
import unittest
from pathlib import Path

from jinja2 import Environment, nodes


class AdminTemplateTests(unittest.TestCase):
    def test_controls_are_only_in_page_block(self):
        source = (
            Path(__file__).resolve().parents[1] / 'templates/satshole/index.html'
        ).read_text()
        template = Environment().parse(source)
        blocks = {block.name: block for block in template.find_all(nodes.Block)}
        for name, block in blocks.items():
            text = ''.join(node.data for node in block.find_all(nodes.TemplateData))
            if name == 'page':
                self.assertIn('Run and entry review', text)
                self.assertIn('Operator audit', text)
                self.assertIn('v-model="actionOpen"', text)
            else:
                self.assertNotIn('<q-', text)
                self.assertNotIn('${', text)
        self.assertEqual(source.count('v-model="actionOpen"'), 1)
        self.assertEqual(source.count('Run and entry review'), 1)


if __name__ == '__main__':
    unittest.main()
