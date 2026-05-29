'''
Obsidian Markdown File Reader and Writer
'''
# standard
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

# Regex patterns for parsing Obsidian markdown files
FRONTMATTER_RE = re.compile(r'\A---\s*\n(.*?)^---\s*\n', re.DOTALL | re.MULTILINE)
WIKILINK_RE = re.compile(r'!\[\[([^\]#|]+)(?:[#|][^\]]*)?\]\]')
MOC_LINE_RE = re.compile(r'^mocs?:\s*\[\[.*\]\]\s*$', re.MULTILINE)
ALIAS_RE = re.compile(r'^aliases:\s*(.+)$', re.MULTILINE)

class Vault(dict):
    '''Maps lowercase name/alias -> Path for all .md files under a vault root.
    Precedence: exact stem match > alias match.'''

    def __init__(self, vault_root: Path, verbose: bool = False):
        '''Walk vault_root recursively and index all .md files by stem and alias.'''
        super().__init__()
        for md_file in Path(vault_root).rglob('*.md'):
            stem = md_file.stem.lower()
            self.setdefault(stem, md_file)
            try:
                content = md_file.read_text(encoding='utf-8', errors='replace')
                m = ALIAS_RE.search(content)
                if m:
                    raw = m.group(1).strip()
                    aliases = [a.strip().strip('"\'') for a in raw.strip('[]').split(',')] \
                              if raw.startswith('[') else [raw]
                    for alias in aliases:
                        self.setdefault(alias.lower(), md_file)
            except OSError:
                pass
        if verbose:
            print(f"[vault] {len(self)} entries from {vault_root}", file=sys.stderr)

    def resolve(self, name: str) -> Path | None:
        '''Return the Path for a given name/alias, or None if not found.'''
        return self.get(name.lower())


class Markdown(list):
    '''Fluent interface for reading, transforming, and writing Markdown files.

    Supports Obsidian-flavoured markdown including wikilink transclusion
    and YAML frontmatter. All transformations return a new Markdown instance;
    the original is never modified.

    Usage:
        Markdown('skeleton.md').front({'tags': ['a', 'b']}).flatten().write('out.md')
    '''

    def __init__(self, thing):
        '''Accept a file path (str/Path), a list of lines, or another Markdown.'''
        super().__init__()
        if isinstance(thing, (str, Path)):
            self.path = Path(thing)
            with open(thing, 'rt', encoding='utf-8') as f:
                for line in f:
                    self.append(line.rstrip('\n'))
        elif isinstance(thing, Markdown):
            self.path = thing.path
            self.extend(thing)
        elif isinstance(thing, list):
            self.path = None
            self.extend(thing)

    def __str__(self) -> str:
        '''Return content as a single string with newline-separated lines.'''
        return '\n'.join(self)

    @property
    def frontmatter(self) -> dict:
        '''Return the YAML frontmatter as a dict, or empty dict if none.'''
        fm, _ = self._parse_fm()
        return fm

    def parent(self) -> Path | None:
        '''Return the parent directory of the file, or None if no path.'''
        return self.path.parent if self.path else None

    def filter(self, f) -> 'Markdown':
        '''Keep only lines for which f returns True, returning a new Markdown.'''
        result = Markdown([line for line in self if f(line)])
        result.path = self.path
        return result

    def word_count(self) -> int:
        '''Count words in the body, stripping frontmatter and markdown syntax.'''
        _, body = self._parse_fm()
        body = re.sub(r'<!--.*?-->', '', body, flags=re.DOTALL)
        body = re.sub(r'^#{1,6}\s+', '', body, flags=re.MULTILINE)
        body = re.sub(r'[*_`~]', '', body)
        body = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', body)
        return len(body.split())

    # ── Transformations (all return a new Markdown) ───────────────────────────

    def _parse_fm(self) -> tuple[dict, str]:
        '''Return (frontmatter_dict, body_text), with empty dict if no frontmatter.'''
        if yaml is None:
            raise ImportError("pip install pyyaml")
        text = str(self)
        m = FRONTMATTER_RE.match(text)
        return (yaml.safe_load(m.group(1)) or {}, text[m.end():]) if m else ({}, text)

    def _build(self, fm_dict: dict, body: str) -> 'Markdown':
        '''Construct a new Markdown from a frontmatter dict and body text.'''
        fm = '---\n' + yaml.dump(fm_dict, default_flow_style=False,
                                  allow_unicode=True, sort_keys=False) + '---\n'
        result = Markdown((fm + body).split('\n'))
        result.path = self.path
        return result

    def defront(self) -> 'Markdown':
        '''Strip all frontmatter, returning a new Markdown.'''
        _, body = self._parse_fm()
        result = Markdown(body.split('\n'))
        result.path = self.path
        return result

    def front(self, data: dict) -> 'Markdown':
        '''Set or replace frontmatter fields. Existing keys not in data are kept.'''
        existing, body = self._parse_fm()
        existing.update(data)
        return self._build(existing, body)

    def upfront(self, data: dict) -> 'Markdown':
        '''Deep-merge into frontmatter: lists are unioned (order-preserving, deduped);
        other values follow the same replace semantics as front().'''
        existing, body = self._parse_fm()
        for key, value in data.items():
            if key in existing and isinstance(existing[key], list) and isinstance(value, list):
                seen = set()
                merged = []
                for item in existing[key] + value:
                    if item not in seen:
                        seen.add(item)
                        merged.append(item)
                existing[key] = merged
            else:
                existing[key] = value
        return self._build(existing, body)

    def flatten(self, vault=None, exclude=None, verbose=False) -> 'Markdown':
        '''Resolve ![[wikilink]] transclusions, stripping frontmatter only from included files.'''
        if vault is None:
            parent = self.parent()
            if parent is None:
                raise ValueError("Cannot flatten without vault if Markdown has no path")
            vault = Vault(parent, verbose=verbose)
        elif not isinstance(vault, Vault):
            vault = Vault(vault, verbose=verbose)

        exclude_set = {e.lower() for e in (exclude or [])}
        text = str(self)

        fm_match = FRONTMATTER_RE.match(text)
        if fm_match:
            frontmatter_block = text[:fm_match.end()]
            body = text[fm_match.end():]
        else:
            frontmatter_block = ''
            body = text

        body = MOC_LINE_RE.sub('', body)

        def replace_transclusion(match):
            '''Resolve a single ![[wikilink]] to its file content.'''
            name = match.group(1).strip()
            if name.lower() in exclude_set:
                if verbose:
                    print(f"[skip]    ![[{name}]]", file=sys.stderr)
                return ''
            target = vault.resolve(name)
            if target is None:
                if verbose:
                    print(f"[MISSING] ![[{name}]]", file=sys.stderr)
                return f'\n<!-- MISSING: ![[{name}]] -->\n'
            if verbose:
                print(f"[ok]      ![[{name}]] -> {target.name}", file=sys.stderr)
            content = target.read_text(encoding='utf-8', errors='replace')
            content = FRONTMATTER_RE.sub('', content, count=1).lstrip()
            content = MOC_LINE_RE.sub('', content)
            return '\n' + content.strip() + '\n'

        flat_body = WIKILINK_RE.sub(replace_transclusion, body).strip()
        result = Markdown((frontmatter_block + flat_body).split('\n'))
        result.path = self.path
        return result

    def do(self, f) -> 'Markdown':
        '''Apply f to each line, returning a new Markdown.'''
        result = Markdown([f(line) for line in self])
        result.path = self.path
        return result

    # ── Output ────────────────────────────────────────────────────────────────

    def write(self, file=None) -> 'Markdown':
        '''Write to file.'''
        target = file or self.path
        if target is None:
            raise ValueError("No output path specified")
        with open(target, 'wt', encoding='utf-8') as f:
            for line in self:
                f.write(line + '\n')
        return Markdown(self)  # Allow chaining after write()

# ── Tests ─────────────────────────────────────────────────────────────────────

class TestMarkdown(unittest.TestCase):
    '''Unit tests for the Markdown class.'''

    def setUp(self):
        '''Create a temp file with two lines for use across tests.'''
        self.line1 = "# Hello World   "
        self.line2 = "   - This is a test markdown file."
        self.path = tempfile.NamedTemporaryFile(
            mode='w+', delete=False, suffix='.md').name
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(f"{self.line1}\n{self.line2}\n")

    def tearDown(self):
        '''Remove the temp file.'''
        os.remove(self.path)

    def test_read(self):
        '''Lines are read without trailing newlines.'''
        md = Markdown(self.path)
        self.assertEqual(md, [self.line1, self.line2])

    def test_write(self):
        '''Written content round-trips back correctly.'''
        new_content = ['# New Title', 'This is new content.']
        Markdown(new_content).write(self.path)
        self.assertEqual(Markdown(self.path), new_content)

    def test_rstrip(self):
        '''do() applies a function to each line.'''
        self.assertEqual(
            Markdown(self.path).do(str.rstrip),
            [self.line1.rstrip(), self.line2])

    def test_front_creates(self):
        '''front() creates frontmatter when none exists.'''
        text = str(Markdown(['# Title', 'body']).front({'tags': ['a', 'b'], 'draft': True}))
        self.assertIn('tags:', text)
        self.assertIn('draft:', text)
        self.assertIn('# Title', text)

    def test_front_keeps_untouched_keys(self):
        '''front() leaves keys not in data alone.'''
        text = str(Markdown(['---', 'title: Old', '---', '# Title']).front({'author': 'Scott'}))
        self.assertIn('title: Old', text)
        self.assertIn('author: Scott', text)

    def test_front_replaces_field(self):
        '''front() overwrites a key that already exists.'''
        text = str(Markdown(['---', 'title: Old', '---', '# Title']).front({'title': 'New'}))
        self.assertIn('title: New', text)
        self.assertNotIn('title: Old', text)

    def test_front_nondestructive(self):
        '''front() does not modify the original.'''
        original = Markdown(['# Title', 'body'])
        original.front({'tags': ['x']})
        self.assertNotIn('tags:', str(original))

    def test_defront_strips_frontmatter(self):
        '''defront() removes the YAML block and leaves the body.'''
        md = Markdown(['---', 'title: Old', '---', '# Title', 'body'])
        text = str(md.defront())
        self.assertNotIn('title:', text)
        self.assertIn('# Title', text)

    def test_defront_then_front_is_nuclear(self):
        '''defront().front() replaces frontmatter entirely.'''
        md = Markdown(['---', 'title: Old', 'author: Scott', '---', '# Title'])
        text = str(md.defront().front({'title': 'New'}))
        self.assertIn('title: New', text)
        self.assertNotIn('author:', text)

    def test_upfront_unions_lists(self):
        '''upfront() merges lists without duplicates, preserving order.'''
        md = Markdown(['---', 'tags:', '- a', '- b', '---', '# Title'])
        text = str(md.upfront({'tags': ['b', 'c']}))
        self.assertIn('- a', text)
        self.assertIn('- b', text)
        self.assertIn('- c', text)
        self.assertEqual(text.count('- b'), 1)

    def test_upfront_replaces_scalars(self):
        '''upfront() still replaces scalar values.'''
        md = Markdown(['---', 'title: Old', '---', '# Title'])
        text = str(md.upfront({'title': 'New'}))
        self.assertIn('title: New', text)
        self.assertNotIn('title: Old', text)

    def test_flatten_resolves_transclusion(self):
        '''![[wikilinks]] are replaced with the content of the target file.'''
        vault_dir = tempfile.mkdtemp()
        included = os.path.join(vault_dir, 'note.md')
        with open(included, 'w', encoding='utf-8') as f:
            f.write('# Included\nsome content\n')
        skeleton = os.path.join(vault_dir, 'main.md')
        with open(skeleton, 'w', encoding='utf-8') as f:
            f.write('# Main\n![[note]]\n')
        result = Markdown(skeleton).flatten()
        text = str(result)
        self.assertIn('some content', text)
        self.assertNotIn('![[note]]', text)

    def test_flatten_preserves_skeleton_frontmatter(self):
        '''The skeleton\'s own frontmatter is kept; included files\' frontmatter is stripped.'''
        vault_dir = tempfile.mkdtemp()
        included = os.path.join(vault_dir, 'note.md')
        with open(included, 'w', encoding='utf-8') as f:
            f.write('---\ntitle: Included\n---\n# Included\nbody\n')
        skeleton = os.path.join(vault_dir, 'main.md')
        with open(skeleton, 'w', encoding='utf-8') as f:
            f.write('---\ntitle: Main\n---\n# Main\n![[note]]\n')
        result = Markdown(skeleton).flatten()
        text = str(result)
        self.assertIn('title: Main', text)
        self.assertNotIn('title: Included', text)

    def test_flatten_missing_transclusion(self):
        '''Unresolved wikilinks become an HTML comment placeholder.'''
        vault_dir = tempfile.mkdtemp()
        skeleton = os.path.join(vault_dir, 'main.md')
        with open(skeleton, 'w', encoding='utf-8') as f:
            f.write('# Main\n![[missing]]\n')
        result = Markdown(skeleton).flatten()
        self.assertIn('MISSING', str(result))

    def test_chain(self):
        '''add_frontmatter().flatten().write() produces a correct combined file.'''
        vault_dir = tempfile.mkdtemp()
        included = os.path.join(vault_dir, 'note.md')
        with open(included, 'w', encoding='utf-8') as f:
            f.write('# Note\ncontent\n')
        skeleton = os.path.join(vault_dir, 'main.md')
        with open(skeleton, 'w', encoding='utf-8') as f:
            f.write('# Main\n![[note]]\n')
        out = os.path.join(vault_dir, 'out.md')
        Markdown(skeleton).front({'tags': ['test']}).flatten().write(out)
        result = Markdown(out)
        text = str(result)
        self.assertIn('tags:', text)
        self.assertIn('content', text)

    def test_frontmatter_property(self):
        '''frontmatter returns parsed dict of YAML fields.'''
        md = Markdown(['---', 'title: Foo', 'tags:', '- a', '- b', '---', '# Body'])
        self.assertEqual(md.frontmatter, {'title': 'Foo', 'tags': ['a', 'b']})

    def test_frontmatter_property_empty(self):
        '''frontmatter returns empty dict when no frontmatter present.'''
        self.assertEqual(Markdown(['# Title']).frontmatter, {})

    def test_filter_keeps_matching_lines(self):
        '''filter() retains only lines satisfying the predicate.'''
        md = Markdown(['# Title', '## Sub', 'plain text', '## Another'])
        result = md.filter(lambda line: line.startswith('## '))
        self.assertEqual(result, ['## Sub', '## Another'])

    def test_filter_nondestructive(self):
        '''filter() does not modify the original.'''
        md = Markdown(['keep', 'drop'])
        md.filter(lambda line: line == 'keep')
        self.assertEqual(len(md), 2)

    def test_word_count(self):
        '''word_count() counts words in body, excluding frontmatter and markdown syntax.'''
        md = Markdown(['---', 'title: Ignored', '---', '# Heading', 'one two three'])
        self.assertEqual(md.word_count(), 4)  # Heading + one + two + three

    def test_word_count_strips_emphasis(self):
        '''word_count() strips markdown emphasis markers.'''
        md = Markdown(['**bold** and *italic*'])
        self.assertEqual(md.word_count(), 3)


if __name__ == '__main__':
    unittest.main()
