# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os
import re
from pathlib import Path

import pypandoc
import sphinx_rtd_theme

THIS_DIR = Path(__file__).parent
print(THIS_DIR)

md_dir = THIS_DIR.parent / "md"


def need_rebuild(sources, generated):
    if not generated.exists():
        return True
    for source in sources:
        if source.stat().st_mtime > generated.stat().st_mtime:
            return True
    return False


for md_file in tuple(md_dir.glob("*.md")):
    src_files = (md_file,)
    if md_file.name == "help-intro.md":
        src_files += ((THIS_DIR / "index_rst_tables"),)
        rst_file = THIS_DIR / "index.rst"
    else:
        rst_file = (THIS_DIR / md_file.name).with_suffix(".rst")
    if need_rebuild(src_files, rst_file):
        print(f"Converting {md_file.name} to reStructuredText format.")
        # rst = reStructuredText; gfm = GitHub Flavored Markdown
        rst_content = pypandoc.convert_file(md_file, "rst", format="gfm")
        rst_content = re.sub(r"help-intro\.md", r"index.md", rst_content)
        rst_content = re.sub(
            r"```([a-z0-9 -]*)`` <([a-z0-9-]*)\.md>`__", r":doc:`\1 <\2>`", rst_content
        )
        # If this doc will be viewed on readthedocs, we want to remove the links
        # to /api and /doc because they will obviously not work.
        # We know if this build script is running on readthedocs servers or not
        # because we define env var LOCAL_SPHINX_BUILD=1 in dev/compile-doc.sh,
        # and this script is only executed when running a local build.
        local_build = os.environ.get("LOCAL_SPHINX_BUILD", "0")
        print("LOCAL_SPHINX_BUILD", local_build)
        if local_build == "0":
            # not a local build => this is a build on readthedocs server
            rst_content = re.sub(r"`(\/api[a-z0-9-/]*) <\1>`__", r"``\1``", rst_content)
            rst_content = re.sub(r"`(\/doc[a-z0-9-/]*) <\1>`__", r"``\1``", rst_content)
        if rst_file.name == "index.rst":
            index_rst_tables = (THIS_DIR / "index_rst_tables").read_text()
            rst_content = f"{rst_content}\n{index_rst_tables}"
        rst_file.write_text(rst_content)

static_dir = THIS_DIR / "_static"
static_dir.mkdir(exist_ok=True)


def get_version():
    code = compile((THIS_DIR / "version.py").read_text(), "<string>", "exec")
    local_env = {}
    eval(code, local_env)
    return local_env["__version__"]


project = "WalT"
copyright = "2012-2023, Members of the WALT project"
author = "Etienne Dublé"
release = get_version()

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = []

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_logo = "logo-walt.png"
html_theme_options = {
    "logo_only": False,
    "style_nav_header_background": "gray",
    "sticky_navigation": False,
}
html_show_sourcelink = False
html_favicon = "logo-walt.png"
