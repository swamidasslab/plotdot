import pandas as pd
import pandas.core.frame
from rdkit.Chem import rdchem
from xenopict import Xenopict
from IPython import get_ipython
import xml.dom.minidom
from pml import HTML

from collections.abc import Sequence


def install():
    register_rdkit()
    register_minidom()
    register_list_mol()


#
# Register minidom formatter so SVG doms display as images.
#


def register_minidom():
    formatter = get_ipython().display_formatter.formatters[  # type: ignore
        "image/svg+xml"
    ]  # ignore
    formatter.for_type(xml.dom.minidom.Document, _minidom_repr_svg)


def _minidom_repr_svg(doc):
    if doc.firstChild.tagName == "svg":
        return doc.toxml()


#
# Patch/register RdKit
#


def _rdkit_repr_html(mol):
    """Formatter that uses Xenopict for rdchem.Mols"""
    return Xenopict(mol).to_html() if isinstance(mol, rdchem.Mol) else mol


def _rdkit_repr_svg(mol):
    """Formatter that uses Xenopict for rdchem.Mols"""
    return Xenopict(mol).to_svg() if isinstance(mol, rdchem.Mol) else mol


def register_rdkit():
    formatter = get_ipython().display_formatter.formatters[  # type: ignore
        "image/svg+xml"
    ]  # ignore
    formatter.for_type(rdchem.Mol, _rdkit_repr_svg)

    rdchem.Mol.__str__ = _rdkit_repr_html
    rdchem.Mol._repr_svg_ = _rdkit_repr_svg


#
# Register list and tuple
#


def _list_mol_html(input):
    if not input or len(input) > 50:
        return repr(input)

    if hasattr(input[0], "_repr_svg_"):
        h = HTML().div(style="display:flex;flex-wrap:wrap;align-items:flex-start")  # type: ignore

        for item in input:
            r = item._repr_svg_() if hasattr(item, "_repr_svg_") else repr(item)
            h.div(style="margin:0.1em;background:white").div(r, escape=False)  # type: ignore
        return str(h)

    return repr(input)


def register_list_mol():
    formatter = get_ipython().display_formatter.formatters[  # type: ignore
        "text/html"
    ]  # ignore
    formatter.for_type(tuple, _list_mol_html)
    formatter.for_type(list, _list_mol_html)


#
# Patch Pandas
#


def _pandas_mol_repr_html(style):
    style.format(_rdkit_repr_html)
    return style


def patch_pandas():
    if not hasattr(pandas.core.frame.DataFrame, "_xenopict"):
        pandas.core.frame.DataFrame._repr_html_orig_ = (  # type: ignore
            pandas.core.frame.DataFrame._repr_html_  # type: ignore
        )
        pandas.core.frame.DataFrame._repr_html_ = _pandas_mol_repr_html  # type: ignore
        pandas.core.frame.DataFrame._xenopict = True  # type: ignore


install()
