# ttypage

A terminal pager for markdown documents and formatted text.

`ttypage` renders markdown in the terminal (headings, lists, tables,
syntax-highlighted code blocks, and mermaid diagrams as text art), lets you
scroll through it, and follow links between markdown files.


## Command line

```
pip install 'ttypage[markdown]'
ttypage README.md
```

Keys:
* `<up>`/`<down>`, `<page-up>`/`<page-down>`: scroll
* `<tab>`/`<shift-tab>`: select a link to another markdown file
* `<enter>`: open the selected link, `<backspace>`: come back
* `<q>`: quit

When the output is not a terminal (e.g., piped to another command), the file
is printed as is.


## Python API

Subclass `ttypage.Pager`, implement `get_page()`, and call `run()`:

```python
from ttypage import Page, Pager

class MyPager(Pager):
    def get_page(self, location, rows, cols):
        return Page(markdown=f"# Hello\n\nYou are at *{location}*.")

MyPager().run("home")
```

A page holds either markdown content (requires the `markdown` extra), or
text already formatted for the terminal (`Page(text=...)`), for instance
source code rendered with `ttypage.code.render_code()`.
Optional hooks: `on_key()`, `resolve_link()`, `get_help_keys()`,
`format_url()`, `diagram_fallback_message()`.

The package without the `markdown` extra only depends on `pygments`.

ttypage was written for the [WalT project](https://walt-project.liglab.fr)
(`walt help show` command, and its trackexec replay tool).
