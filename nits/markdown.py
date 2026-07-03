'''
Obsidian Markdown File Reader and Writer
Supports LaTeX conversion.
'''
# standard
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
import yaml

# Regex patterns for parsing Obsidian markdown files
FRONTMATTER_RE = re.compile(r'\A---\s*\n(.*?)^---\s*\n', re.DOTALL | re.MULTILINE)
WIKILINK_RE    = re.compile(r'!\[\[([^\]#|]+)(?:[#|][^\]]*)?\]\]')
MOC_LINE_RE    = re.compile(r'^mocs?:\s*\[\[.*\]\]\s*$', re.MULTILINE)
ALIAS_RE       = re.compile(r'^aliases:\s*(.+)$', re.MULTILINE)
CITATION_RE    = re.compile(r'\[\[([^\]#|]+)#\^([^\]|]+)(?:\|[^\]]*)?\]\]')
ANCHOR_RE      = re.compile(r'\^([\w-]+)\s*$', re.MULTILINE)
COMMENT_RE     = re.compile(r'%%.*?%%', re.DOTALL)
NOCITE_RE      = re.compile(r'%%\s*nocite:\s*\^([\w-]+)\s*%%')

# LaTeX conversion
CALLOUT_HDR_RE  = re.compile(r'^> \[!(\w+)\]\s*(.*)')
BLOCKQUOTE_RE   = re.compile(r'^> ?(.*)')
BULLET_RE       = re.compile(r'^([ \t]*)[-*+] (.*)')
ORDERED_RE      = re.compile(r'^([ \t]*)\d+\. (.*)')
HEADING_MD_RE   = re.compile(r'^(#{1,6}) (.*)')
BOLD_MD_RE      = re.compile(r'\*\*(.+?)\*\*')
ITALIC_STAR_RE  = re.compile(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)')
ITALIC_UNDER_RE = re.compile(r'(?<!\w)_(.+?)_(?!\w)')
FN_DEF_RE       = re.compile(r'^\[\^([\w-]+)\]:\s*(.*)')
FN_REF_RE       = re.compile(r'\[\^([\w-]+)\]')
WIKI_DISP_RE    = re.compile(r'!?\[\[[^\]]*\|([^\]]+)\]\]')
WIKI_BARE_RE    = re.compile(r'!?\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]')
MD_LINK_RE      = re.compile(r'\[([^\]]+)\]\([^)]*\)')
_HEADING_CMDS   = [
    'section', 'subsection', 'subsubsection', 'paragraph', 'subparagraph', 'subparagraph']
_REF_HDR_RE     = re.compile(r'^#{1,2} References\s*$', re.MULTILINE)
HR_RE            = re.compile(r'^-{3,}$')
_ABSTRACT_HDR_RE = re.compile(r'^# Abstract[ \t]*$', re.MULTILINE | re.IGNORECASE)
_TITLE_HDR_RE    = re.compile(r'^# .+$', re.MULTILINE)
_ANY_HDR_RE      = re.compile(r'^#{1,6} ', re.MULTILINE)

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


def _latex_preamble(fm: dict, doc_class: str,
                    preprint: bool = True,
                    callout_env: str = 'quote',
                    macros_file: str | None = None) -> str:
    lines = [f'\\documentclass{{{doc_class}}}', '', '\\usepackage{microtype}', '']
    if callout_env == 'mdframed':
        lines += ['\\usepackage{mdframed}', '']
    if macros_file:
        lines += [f'\\input{{{macros_file}}}', '']

    def _cmd(name, val):
        if val:
            lines.append(f'\\{name}{{{val}}}')

    lines.append(f'\\title{{{fm.get("title", "")}}}')  # always emit \title{}
    _cmd('author',      fm.get('author', ''))
    _cmd('affiliation', fm.get('affiliation', ''))
    _cmd('contact',     fm.get('contact', ''))
    abstract = str(fm.get('abstract', '') or '')
    if abstract:
        lines.append(f'\\textofabstract{{%\n{abstract}\n}}%')
    _cmd('articledoi', str(fm.get('doi', fm.get('articledoi', '')) or ''))
    vol   = str(fm.get('volume', '') or '')
    issue = str(fm.get('issue',  '') or '')
    year  = str(fm.get('year',   '') or '')
    if any((vol, issue, year)):
        lines.append(f'\\volumeissueyear{{{vol}}}{{{issue}}}{{{year}}}')
    lines.append('\\setcounter{page}{1}')
    if preprint:
        lines += [
            '',
            '% preprint: strip journal headers/footers, keep centred page number',
            '\\fancyhf{}',
            '\\fancyfoot[C]{\\thepage}',
            '\\renewcommand{\\headrulewidth}{0pt}',
            '\\renewcommand{\\footrulewidth}{0pt}',
            '\\fancypagestyle{plain}{\\fancyhf{}\\fancyfoot[C]{\\thepage}'
            '\\renewcommand{\\headrulewidth}{0pt}'
            '\\renewcommand{\\footrulewidth}{0pt}}',
        ]
    # Remove ergoclass dot after section numbers (requires @ access)
    lines += [
        '',
        '\\makeatletter',
        '\\renewcommand*{\\@seccntformat}[1]{\\csname the#1\\endcsname\\quad}',
        '\\makeatother',
        '',
    ]
    return '\n'.join(lines) + '\n'


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

    @staticmethod
    def _parse_ref_dict(ref_md: 'Markdown') -> dict:
        '''Parse a references Markdown into {anchor: citation_text}.
        Strips frontmatter and Obsidian %% comments %% before parsing.'''
        text = str(ref_md)
        text = FRONTMATTER_RE.sub('', text, count=1)
        text = COMMENT_RE.sub('', text)
        ref_dict = {}
        for para in re.split(r'\n\s*\n', text):
            para = para.strip()
            m = ANCHOR_RE.search(para)
            if m:
                citation = para[:m.start()].strip()
                if citation:
                    ref_dict[m.group(1)] = citation
        return ref_dict

    def references(self, ref_file, heading: str = '# References') -> 'Markdown':
        '''Append a References section for all [[file#^anchor]] citations in the body.
        Also includes any %%nocite: ^anchor%% declarations.
        Looks up each anchor in ref_file and appends sorted, deduplicated citations.'''
        ref_md = ref_file if isinstance(ref_file, Markdown) else Markdown(ref_file)
        ref_dict = Markdown._parse_ref_dict(ref_md)
        text = str(self)
        cited = {}
        for m in CITATION_RE.finditer(text):
            anchor = m.group(2).strip()
            if anchor not in cited:
                cited[anchor] = ref_dict.get(anchor)
        for m in NOCITE_RE.finditer(text):
            anchor = m.group(1).strip()
            if anchor not in cited:
                cited[anchor] = ref_dict.get(anchor)
        refs = sorted((v for v in cited.values() if v), key=str.casefold)
        if not refs:
            return Markdown(self)
        lines = list(self) + ['', heading, ''] + [line for ref in refs for line in (ref, '')]
        result = Markdown(lines)
        result.path = self.path
        return result

    def narrow(self, heading: str, level: int = 1) -> 'Markdown':
        '''Extract all sections whose heading matches at the given level (case-insensitive).
        A section runs from its heading line to the next heading at the same or higher level.'''
        prefix = '#' * level + ' '
        end_re = re.compile(r'^#{1,' + str(level) + r'} ')
        lines = list(self)
        sections = []
        i = 0
        while i < len(lines):
            if lines[i].startswith(prefix) and \
                    lines[i][len(prefix):].strip().lower() == heading.lower():
                section = [lines[i]]
                i += 1
                while i < len(lines) and not end_re.match(lines[i]):
                    section.append(lines[i])
                    i += 1
                sections.append(section)
            else:
                i += 1
        result_lines = []
        for j, section in enumerate(sections):
            if j > 0:
                result_lines.append('')
            result_lines.extend(section)
        result = Markdown(result_lines)
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

    # ── LaTeX conversion ──────────────────────────────────────────────────────

    def _latex_inline(self, text: str, footnotes: dict) -> str:
        '''
        Convert inline Markdown to LaTeX: strip wikilinks,
        convert bold/italic, escape special chars.
        '''
        text = WIKI_DISP_RE.sub(r'\1', text)
        text = WIKI_BARE_RE.sub(r'\1', text)
        text = MD_LINK_RE.sub(r'\1', text)

        def _sub_fn(m):
            raw = footnotes.get(m.group(1), m.group(1))
            return r'\footnote{' + self._latex_inline(raw, {}) + '}'

        text = FN_REF_RE.sub(_sub_fn, text)
        text = BOLD_MD_RE.sub(r'\\textbf{\1}', text)
        text = ITALIC_STAR_RE.sub(r'\\textit{\1}', text)
        text = ITALIC_UNDER_RE.sub(r'\\textit{\1}', text)
        text = text.replace('&', r'\&')
        text = text.replace('%', r'\%')
        return text

    def _to_latex_table(self, rows: list) -> str:
        '''Convert a list of Markdown pipe-row strings to a LaTeX tabular.'''
        def parse_row(line):
            return [c.strip() for c in line.split('|')[1:-1]]

        def col_align(cell):
            s = cell.strip()
            if s.startswith(':') and s.rstrip('-').endswith(':'):
                return 'c'
            if s.rstrip('-').endswith(':'):
                return 'r'
            return 'l'

        sep_idx = next(
            (i for i, r in enumerate(rows)
             if all(re.match(r'^:?-+:?$', c.strip()) for c in parse_row(r))),
            1
        )
        headers   = parse_row(rows[sep_idx - 1]) if sep_idx > 0 else []
        sep_cells = parse_row(rows[sep_idx])
        data_rows = [parse_row(r) for r in rows[sep_idx + 1:]]
        spec = ''.join(col_align(c) for c in sep_cells)
        out = [
            '\\begingroup',
            '\\renewcommand{\\arraystretch}{1.4}',
            '\\setlength{\\tabcolsep}{8pt}',
            '\\begin{center}',
            f'\\begin{{tabular}}{{{spec}}}',
            '\\hline',
        ]
        if headers:
            out.append(' & '.join(
                f'\\textbf{{{self._latex_inline(h, {})}}}' for h in headers) + r' \\')
            out.append('\\hline')
        for row in data_rows:
            out.append(' & '.join(self._latex_inline(c, {}) for c in row) + r' \\')
        out.append('\\hline')
        out.append('\\end{tabular}')
        out.append('\\end{center}')
        out.append('\\endgroup')
        return '\n'.join(out)

    def _to_latex_refs(self, text: str, footnotes: dict) -> str:
        '''Format a references block as a hanging-indent LaTeX list.'''
        paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
        if not paras:
            return ''
        out = [
            '\\section*{References}',
            '\\begin{list}{}{\\setlength{\\leftmargin}{0.25in}'
            '\\setlength{\\itemindent}{-0.25in}'
            '\\setlength{\\parsep}{2pt plus 1pt}'
            '\\setlength{\\itemsep}{0pt}}',
        ]
        for para in paras:
            para = ANCHOR_RE.sub('', para).strip()
            if para:
                out.append(f'\\item {self._latex_inline(para, footnotes)}')
        out.append('\\end{list}')
        return '\n'.join(out) + '\n'

    def _to_latex_body(self, lines: list, footnotes: dict,
                       callout_env: str = 'quote',
                       use_gv: bool = False) -> str:
        '''Convert Markdown body lines to a LaTeX body string.

        Heading convention: # is special (title/abstract/references — stripped
        in pre-processing; any remaining # → \\section*{}). ## → \\section{},
        ### → \\subsection{}, #### → \\subsubsection{}.
        '''
        out: list[str] = []
        i = 0
        list_stack: list[tuple[str, int]] = []  # (type 'u'|'o', indent)

        def end_list():
            while list_stack:
                ltype, _ = list_stack.pop()
                out.append('\\end{itemize}' if ltype == 'u' else '\\end{enumerate}')

        def sync_list(ltype: str, indent: int) -> None:
            while list_stack and list_stack[-1][1] > indent:
                t, _ = list_stack.pop()
                out.append('\\end{itemize}' if t == 'u' else '\\end{enumerate}')
            if list_stack and list_stack[-1][1] == indent and list_stack[-1][0] != ltype:
                t, _ = list_stack.pop()
                out.append('\\end{itemize}' if t == 'u' else '\\end{enumerate}')
            if not list_stack or list_stack[-1][1] < indent:
                list_stack.append((ltype, indent))
                out.append('\\begin{itemize}' if ltype == 'u' else '\\begin{enumerate}')

        def il(t: str) -> str:
            return self._latex_inline(t, footnotes)

        while i < len(lines):
            line = lines[i]

            if ANCHOR_RE.match(line.strip()):
                i += 1
                continue

            if not line.strip():
                end_list()
                out.append('')
                i += 1
                continue

            # Thematic break ---
            if HR_RE.match(line.strip()):
                end_list()
                out.append(r'\gvbreak' if use_gv else (
                    r'\vskip 1em\noindent\hfil'
                    r'\rule{1.5in}{0.4pt}\enspace$\diamond$\enspace'
                    r'\rule{1.5in}{0.4pt}\hfil\vskip 1em'
                ))
                i += 1
                continue

            m = HEADING_MD_RE.match(line)
            if m:
                end_list()
                level = len(m.group(1))
                heading_text = m.group(2).strip()
                if level == 1:
                    # Top-level: pre-processing removed title/abstract/references;
                    # anything remaining is an unnumbered section separator.
                    lname = heading_text.lower()
                    if lname not in ('abstract', 'references', 'bibliography'):
                        out.append(f'\\section*{{{il(heading_text)}}}')
                else:
                    # ## → \section (idx 0), ### → \subsection (idx 1), etc.
                    cmd = _HEADING_CMDS[min(level - 2, len(_HEADING_CMDS) - 1)]
                    out.append(f'\\{cmd}{{{il(heading_text)}}}')
                i += 1
                continue

            # Pipe table
            if line.startswith('|'):
                end_list()
                table_rows = [line]
                i += 1
                while i < len(lines) and lines[i].startswith('|'):
                    table_rows.append(lines[i])
                    i += 1
                out.append(self._to_latex_table(table_rows))
                continue

            m = CALLOUT_HDR_RE.match(line)
            if m:
                end_list()
                ctype  = m.group(1).lower()
                ctitle = m.group(2).strip()
                i += 1
                body_parts: list[str] = []
                while i < len(lines) and lines[i].startswith('>') \
                        and not CALLOUT_HDR_RE.match(lines[i]):
                    bm = BLOCKQUOTE_RE.match(lines[i])
                    content = bm.group(1) if bm else lines[i]
                    if not HR_RE.match(content.strip()):
                        body_parts.append(content)
                    i += 1
                body_str = self._to_latex_body(
                    body_parts, footnotes, callout_env, use_gv).strip()
                if use_gv and ctitle:
                    env = 'gvtom' if ctype == 'warning' else 'gvdef'
                    out.append(f'\\begin{{{env}}}{{{il(ctitle)}}}')
                    out.append(body_str)
                    out.append(f'\\end{{{env}}}')
                else:
                    label = f'\\textit{{{il(ctitle)}.}} ' if ctitle else ''
                    env = callout_env if not use_gv else 'quote'
                    out.append(f'\\begin{{{env}}}')
                    out.append(f'{label}{body_str}')
                    out.append(f'\\end{{{env}}}')
                continue

            m = BLOCKQUOTE_RE.match(line)
            if m:
                end_list()
                bq_parts: list[str] = [m.group(1)]
                i += 1
                while i < len(lines) and BLOCKQUOTE_RE.match(lines[i]) \
                        and not CALLOUT_HDR_RE.match(lines[i]):
                    bq_parts.append(BLOCKQUOTE_RE.match(lines[i]).group(1)) # TODO: what if no match?
                    i += 1
                paras, cur = [], []
                for bp in bq_parts:
                    if bp.strip():
                        cur.append(bp)
                    else:
                        if cur:
                            paras.append(il(' '.join(cur)))
                            cur = []
                if cur:
                    paras.append(il(' '.join(cur)))
                body_str = '\n\n'.join(f'\\textit{{{p}}}' for p in paras)
                out.append('\\begin{quote}')
                out.append(body_str)
                out.append('\\end{quote}')
                continue

            m = BULLET_RE.match(line)
            if m:
                sync_list('u', len(m.group(1).expandtabs(4)))
                out.append(f'\\item {il(m.group(2))}')
                i += 1
                continue

            m = ORDERED_RE.match(line)
            if m:
                sync_list('o', len(m.group(1).expandtabs(4)))
                out.append(f'\\item {il(m.group(2))}')
                i += 1
                continue

            end_list()
            out.append(il(line))
            i += 1

        end_list()
        return '\n'.join(out) + '\n'

    def to_latex(self, doc_class: str = 'ergoclass',
                 preprint: bool = True,
                 callout_env: str = 'quote',
                 macros_file: str | None = None) -> str:
        '''Generate a complete LaTeX document string from this Markdown.

        doc_class:   LaTeX document class (default 'ergoclass').
        preprint:    Strip journal headers/footers; keep centred page number (default True).
        callout_env: LaTeX environment for untitled callouts: 'quote' (default) or 'mdframed'.
                     Ignored for titled callouts when macros_file is set.
        macros_file: Stem of a .tex macros file to \\input (e.g. 'gv-tex-macros').
                     When set, titled [!note] → \\gvdef, [!warning] → \\gvcf,
                     and --- → \\gvbreak instead of the diamond rule.

        Heading convention: # Title/Abstract/References are handled specially
        (see pre-processing below). ## → \\section{}, ### → \\subsection{}, etc.

        Frontmatter keys consumed: title, author, affiliation, contact, abstract,
        doi/articledoi, volume, issue, year.
        '''
        fm, body = self._parse_fm()
        fm = dict(fm)  # local copy so we can update without mutating

        footnotes: dict[str, str] = {}
        body_lines: list[str] = []
        for line in body.split('\n'):
            mn = FN_DEF_RE.match(line)
            if mn:
                footnotes[mn.group(1)] = mn.group(2)
            else:
                body_lines.append(line)
        clean = COMMENT_RE.sub('', '\n'.join(body_lines))

        # ── Pre-processing: extract special # headings ────────────────────────
        # 1. Extract # Abstract section → fm['abstract'] (if not already set)
        am = _ABSTRACT_HDR_RE.search(clean)
        if am:
            rest = clean[am.end():]
            next_h = _ANY_HDR_RE.search(rest)
            abs_content = (rest[:next_h.start()] if next_h else rest).strip()
            if not fm.get('abstract'):
                fm['abstract'] = abs_content
            clean = clean[:am.start()] + (rest[next_h.start():] if next_h else '')

        # 2. Remove first # Title heading from body (use as fm['title'] if unset)
        #    Skip reserved headings (references/bibliography — handled in step 3)
        _reserved = {'references', 'bibliography'}
        for tm in _TITLE_HDR_RE.finditer(clean):
            extracted = tm.group(0)[2:].strip()  # strip leading '# '
            if extracted.lower() in _reserved:
                continue
            if not fm.get('title'):
                fm['title'] = extracted
            clean = clean[:tm.start()] + clean[tm.end():]
            break

        # 3. Split # References section (existing)
        use_gv = macros_file is not None
        rm = _REF_HDR_RE.search(clean)
        if rm:
            main_latex = self._to_latex_body(
                clean[:rm.start()].split('\n'), footnotes, callout_env, use_gv)
            refs_latex = self._to_latex_refs(clean[rm.end():], footnotes)
        else:
            main_latex = self._to_latex_body(
                clean.split('\n'), footnotes, callout_env, use_gv)
            refs_latex = ''

        for key in ('abstract', 'title', 'author', 'affiliation'):
            if fm.get(key):
                fm[key] = self._latex_inline(str(fm[key]), footnotes)
        preamble = _latex_preamble(fm, doc_class, preprint, callout_env, macros_file)
        return (preamble
                + '\\begin{document}\n\n\\maketitle\n\n'
                + main_latex
                + refs_latex
                + '\n\\end{document}\n')

    def write_latex(self, file, doc_class: str = 'ergoclass',
                    preprint: bool = True,
                    callout_env: str = 'quote',
                    macros_file: str | None = None) -> 'Markdown':
        '''Write a complete LaTeX document to file; returns self for chaining.'''
        with open(file, 'wt', encoding='utf-8') as f:
            f.write(self.to_latex(doc_class=doc_class, preprint=preprint,
                                   callout_env=callout_env, macros_file=macros_file))
        return Markdown(self)

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

    def test_references_appends_section(self):
        '''references() appends a # References section for cited anchors.'''
        ref = Markdown([
            'Smith, J. (2000). A great paper. *Journal*, 1(1), 1–10.',
            '^smith2000-great-paper',
            '',
            'Jones, A. (2010). Another paper. *Journal*, 2(2), 20–30.',
            '^jones2010-another-paper',
        ])
        md = Markdown(['See [[refs#^smith2000-great-paper|Smith, 2000]] for details.'])
        result = str(md.references(ref))
        self.assertIn('# References', result)
        self.assertIn('Smith, J.', result)
        self.assertNotIn('Jones, A.', result)

    def test_references_sorted(self):
        '''references() sorts citations alphabetically.'''
        ref = Markdown([
            'Zola, E. (1880). A novel. Publisher.',
            '^zola1880',
            '',
            'Austen, J. (1813). Another novel. Publisher.',
            '^austen1813',
        ])
        md = Markdown([
            'See [[r#^zola1880|Zola]] and [[r#^austen1813|Austen]].'
        ])
        refs_section = str(md.references(ref)).rsplit('# References', maxsplit=1)[-1]
        self.assertLess(refs_section.index('Austen'), refs_section.index('Zola'))

    def test_references_deduplicates(self):
        '''references() includes each citation only once even if cited multiple times.'''
        ref = Markdown(['Smith, J. (2000). Paper. *Journal*.', '^smith2000'])
        md = Markdown(['[[r#^smith2000|Smith]] and [[r#^smith2000|Smith]] again.'])
        result = str(md.references(ref))
        self.assertEqual(result.count('Smith, J.'), 1)

    def test_references_strips_obsidian_comments(self):
        '''references() ignores %% comment blocks in the reference file.'''
        ref = Markdown([
            '%%',
            'This is a comment.',
            '%%',
            'Brown, C. (1990). Paper. *Journal*.',
            '^brown1990',
        ])
        md = Markdown(['See [[r#^brown1990|Brown, 1990]].'])
        result = str(md.references(ref))
        self.assertIn('Brown, C.', result)
        self.assertNotIn('comment', result)

    def test_references_nondestructive(self):
        '''references() does not modify the original.'''
        ref = Markdown(['Smith, J. (2000). Paper.', '^smith2000'])
        md = Markdown(['[[r#^smith2000|Smith, 2000]]'])
        md.references(ref)
        self.assertNotIn('# References', str(md))

    def test_nocite_includes_uncited_reference(self):
        '''%%nocite: ^anchor%% forces a reference into the section even without inline citation.'''
        ref = Markdown([
            'Smith, J. (2000). Paper. *Journal*.',
            '^smith2000',
            '',
            'Jones, A. (2010). Background work. *Journal*.',
            '^jones2010',
        ])
        md = Markdown([
            'Main text with no inline citation.',
            '%%nocite: ^jones2010%%',
        ])
        result = str(md.references(ref))
        self.assertIn('Jones, A.', result)
        self.assertNotIn('Smith, J.', result)

    def test_nocite_combined_with_inline_citations(self):
        '''nocite and inline citations both appear in the References section.'''
        ref = Markdown([
            'Smith, J. (2000). Paper. *Journal*.',
            '^smith2000',
            '',
            'Jones, A. (2010). Background work. *Journal*.',
            '^jones2010',
        ])
        md = Markdown([
            'See [[r#^smith2000|Smith, 2000]].',
            '%%nocite: ^jones2010%%',
        ])
        result = str(md.references(ref))
        self.assertIn('Smith, J.', result)
        self.assertIn('Jones, A.', result)

    def test_narrow_extracts_section(self):
        '''narrow() returns lines from the matched heading to the next same-level heading.'''
        md = Markdown([
            '# Introduction', 'intro text',
            '# Methods', 'methods text', '## Sub', 'sub text',
            '# Results', 'results text',
        ])
        result = md.narrow('Methods')
        self.assertEqual(result[0], '# Methods')
        self.assertIn('methods text', result)
        self.assertIn('## Sub', result)
        self.assertIn('sub text', result)
        self.assertNotIn('# Introduction', result)
        self.assertNotIn('# Results', result)

    def test_narrow_multiple_sections(self):
        '''narrow() collects all sections with the same heading.'''
        md = Markdown([
            '# Notes', 'first notes',
            '# Other', 'other text',
            '# Notes', 'second notes',
        ])
        result = md.narrow('Notes')
        self.assertIn('first notes', result)
        self.assertIn('second notes', result)
        self.assertNotIn('other text', result)

    def test_narrow_case_insensitive(self):
        '''narrow() matches headings case-insensitively.'''
        md = Markdown(['# METHODS', 'content', '# Results', 'other'])
        self.assertIn('content', md.narrow('methods'))

    def test_narrow_level(self):
        '''narrow() respects the heading level parameter.'''
        md = Markdown([
            '# Top', 'top text',
            '## Detail', 'detail text', '### Sub', 'sub text',
            '## Other', 'other text',
        ])
        result = md.narrow('Detail', level=2)
        self.assertIn('detail text', result)
        self.assertIn('### Sub', result)
        self.assertNotIn('other text', result)

    def test_narrow_nondestructive(self):
        '''narrow() does not modify the original.'''
        md = Markdown(['# Section', 'content', '# Other', 'other'])
        md.narrow('Section')
        self.assertEqual(len(md), 4)

    def test_to_latex_document_structure(self):
        '''to_latex() wraps body in document environment with maketitle.'''
        result = Markdown(['Hello.']).to_latex()
        self.assertIn('\\begin{document}', result)
        self.assertIn('\\maketitle', result)
        self.assertIn('\\end{document}', result)

    def test_to_latex_frontmatter_preamble(self):
        '''to_latex() maps frontmatter keys to document class commands.'''
        md = Markdown(['---', 'title: My Paper', 'author: Scott James', '---', 'Body.'])
        result = md.to_latex()
        self.assertIn('\\title{My Paper}', result)
        self.assertIn('\\author{Scott James}', result)

    def test_to_latex_heading(self):
        '''# is title (removed); ## → \\section; ### → \\subsection.'''
        md = Markdown(['# Paper Title', '## Section One', '### A Sub', 'Text.'])
        result = md.to_latex()
        self.assertNotIn('\\section{Paper Title}', result)  # title removed from body
        self.assertIn('\\section{Section One}', result)
        self.assertIn('\\subsection{A Sub}', result)

    def test_to_latex_title_from_heading(self):
        '''# heading sets \\title{} when frontmatter has no title.'''
        md = Markdown(['# My Paper', '## Intro', 'Content.'])
        result = md.to_latex()
        self.assertIn('\\title{My Paper}', result)

    def test_to_latex_abstract_extracted(self):
        '''# Abstract section becomes \\textofabstract{} and is removed from body.'''
        md = Markdown(['# Abstract', 'The abstract text.', '', '## Intro', 'Content.'])
        result = md.to_latex()
        self.assertIn('The abstract text.', result.split('\\begin{document}')[0])
        self.assertNotIn('\\section{Abstract}', result)
        self.assertNotIn('\\section*{Abstract}', result)

    def test_to_latex_level_shift(self):
        '''## is numbered \\section; ### is \\subsection (no top-level # numbering).'''
        md = Markdown(['## First', '## Second', '### Sub'])
        result = md.to_latex()
        self.assertIn('\\section{First}', result)
        self.assertIn('\\section{Second}', result)
        self.assertIn('\\subsection{Sub}', result)

    def test_to_latex_bold_italic(self):
        '''to_latex() converts **bold** and *italic* inline.'''
        md = Markdown(['**bold** and *italic*.'])
        result = md.to_latex()
        self.assertIn('\\textbf{bold}', result)
        self.assertIn('\\textit{italic}', result)

    def test_to_latex_always_has_title(self):
        '''to_latex() always emits \\title{} even without a title in frontmatter.'''
        result = Markdown(['Body.']).to_latex()
        self.assertIn('\\title{', result)

    def test_to_latex_callout_no_type_label(self):
        '''to_latex() callouts use only the title, omitting the Obsidian type (note/warning).'''
        md = Markdown(['> [!note] The Hard Problem', '> Why is there experience?'])
        result = md.to_latex()
        self.assertIn('\\begin{quote}', result)
        self.assertIn('\\textit{The Hard Problem.}', result)
        self.assertNotIn('Note:', result)
        self.assertIn('Why is there experience?', result)

    def test_to_latex_callout_no_title(self):
        '''to_latex() callouts without a title produce no italic label.'''
        md = Markdown(['> [!note]', '> Just the body.'])
        result = md.to_latex()
        inside = result.split('\\begin{quote}')[-1].split('\\end{quote}')[0]
        self.assertNotIn('\\textit{', inside)
        self.assertIn('Just the body.', inside)

    def test_to_latex_horizontal_rule(self):
        '''to_latex() converts --- to a decorative diamond rule by default.'''
        md = Markdown(['Before.', '', '---', '', 'After.'])
        result = md.to_latex()
        self.assertIn('diamond', result)
        self.assertNotIn('\n---\n', result)

    def test_to_latex_gv_macros_break(self):
        '''macros_file set: --- → \\gvbreak instead of diamond rule.'''
        md = Markdown(['Before.', '', '---', '', 'After.'])
        result = md.to_latex(macros_file='gv-tex-macros')
        self.assertIn('\\gvbreak', result)
        self.assertNotIn('diamond', result)

    def test_to_latex_gv_macros_callout(self):
        '''macros_file set: [!note] title → \\begin{gvdef}{title}...\\end{gvdef}.'''
        md = Markdown(['> [!note] Exp Exists', '> E occurs.'])
        result = md.to_latex(macros_file='gv-tex-macros')
        self.assertIn('\\begin{gvdef}{Exp Exists}', result)
        self.assertIn('\\end{gvdef}', result)

    def test_to_latex_callout_with_bullets(self):
        '''Bullet list inside a callout body renders as itemize.'''
        md = Markdown(['> [!note] Title', '> - Alpha', '> - Beta'])
        result = md.to_latex(macros_file='gv-tex-macros')
        self.assertIn('\\begin{itemize}', result)
        self.assertIn('\\item Alpha', result)
        self.assertIn('\\item Beta', result)

    def test_to_latex_gv_macros_warning(self):
        '''macros_file set: [!warning] title → \\begin{gvtom}{title}...\\end{gvtom}.'''
        md = Markdown(['> [!warning] Dual Aspect', '> Compare DAT.'])
        result = md.to_latex(macros_file='gv-tex-macros')
        self.assertIn('\\begin{gvtom}{Dual Aspect}', result)
        self.assertIn('\\end{gvtom}', result)

    def test_to_latex_gv_macros_input(self):
        '''macros_file set: \\input{file} appears in preamble.'''
        result = Markdown(['Body.']).to_latex(macros_file='gv-tex-macros')
        self.assertIn('\\input{gv-tex-macros}', result)

    def test_to_latex_hr_stripped_in_callout(self):
        '''to_latex() strips --- lines inside callout bodies.'''
        md = Markdown(['> [!note] Title', '> Before.', '> ---', '> After.'])
        result = md.to_latex()
        inside = result.split('\\begin{quote}')[-1].split('\\end{quote}')[0]
        self.assertNotIn('\\rule', inside)

    def test_to_latex_table(self):
        '''to_latex() converts pipe tables to LaTeX tabular with bold headers.'''
        md = Markdown(['| A | B |', '| --- | --- |', '| 1 | 2 |'])
        result = md.to_latex()
        self.assertIn('\\begin{tabular}', result)
        self.assertIn('\\hline', result)
        self.assertIn('\\textbf{A}', result)
        self.assertIn('1 & 2', result)

    def test_to_latex_preprint_clears_headers(self):
        '''to_latex(preprint=True) emits fancyhf{} to suppress journal headers.'''
        self.assertIn('\\fancyhf{}', Markdown(['Body.']).to_latex(preprint=True))
        self.assertNotIn('\\fancyhf{}', Markdown(['Body.']).to_latex(preprint=False))

    def test_to_latex_section_dot_removed(self):
        '''to_latex() overrides ergoclass \\@seccntformat to remove the dot.'''
        result = Markdown(['Body.']).to_latex()
        self.assertIn('\\@seccntformat', result)

    def test_to_latex_footnote(self):
        '''to_latex() converts [^label] refs to \\footnote{} using def text.'''
        md = Markdown(['Text[^note] here.', '[^note]: The footnote text.'])
        result = md.to_latex()
        self.assertIn('\\footnote{The footnote text.}', result)
        self.assertNotIn('[^note]', result)

    def test_to_latex_wikilink_citation(self):
        '''to_latex() reduces [[ref#^key|display]] to display text.'''
        md = Markdown(['See ([[refs#^smith2000|Smith, 2000]]) for details.'])
        result = md.to_latex()
        self.assertIn('Smith, 2000', result)
        self.assertNotIn('[[', result)

    def test_to_latex_list(self):
        '''to_latex() wraps bullet items in itemize environment.'''
        md = Markdown(['- First', '- Second'])
        result = md.to_latex()
        self.assertIn('\\begin{itemize}', result)
        self.assertIn('\\item First', result)
        self.assertIn('\\end{itemize}', result)

    def test_to_latex_nested_list(self):
        '''to_latex() opens a nested itemize for indented sub-bullets.'''
        md = Markdown(['- Top', '  - Sub', '- Top2'])
        result = md.to_latex()
        self.assertEqual(result.count('\\begin{itemize}'), 2)
        self.assertEqual(result.count('\\end{itemize}'), 2)
        self.assertIn('\\item Top', result)
        self.assertIn('\\item Sub', result)

    def test_to_latex_references_section(self):
        '''to_latex() after references() produces a hanging-indent list.'''
        ref = Markdown(['Smith, J. (2000). *A Paper.* Journal.', '^smith2000'])
        md = Markdown(['See [[r#^smith2000|Smith, 2000]].'])
        result = md.references(ref).to_latex()
        self.assertIn('\\section*{References}', result)
        self.assertIn('\\item Smith, J.', result)
        self.assertNotIn('^smith2000', result)


if __name__ == '__main__':
    unittest.main()
