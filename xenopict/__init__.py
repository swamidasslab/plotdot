from __future__ import annotations
import numpy as np
from typing import Callable
from xml.dom.minidom import parseString
import contextlib
from six.moves.collections_abc import Sequence, Mapping
from rdkit.Chem.Draw import rdMolDraw2D, rdDepictor
from rdkit.Chem.rdchem import Mol
from rdkit.Chem import MolFromSmiles, MolFromSmarts
from .colormap import ColorInterpolator, reds, blues, greens, purples, white, oranges
from .plotdot import PlotDot
from ._version import __version__
from matplotlib.cm import get_cmap
from matplotlib.colors import Colormap
from urllib.parse import quote


with contextlib.suppress(NameError):
    del _version


with contextlib.suppress(ImportError):
    from shapely.geometry import LineString, Point, Polygon


def install_colormaps():
    _ci = ColorInterpolator()

    _colormap = _ci.diverging_swatch(white, blues, reds)
    _ci.to_matlab_colormap(_colormap, "xenosite_bwr", register=True)
    _ci.to_matlab_colormap(_colormap, "xenosite", register=True)

    _colormap = _ci.diverging_swatch(white, greens, purples)
    _ci.to_matlab_colormap(_colormap, "xenosite_gwp", register=True)

    _colormap = _ci.diverging_swatch(white, purples, oranges)
    _ci.to_matlab_colormap(_colormap, "xenosite_pwo", register=True)


install_colormaps()

__all__ = ["shaded_svg", "Xenopict"]


ColorMapType = Callable[[float], Sequence[float]]
AtomIdx = int
BondShading = tuple[Sequence[AtomIdx], Sequence[AtomIdx], Sequence[float]]
AtomShading = Sequence[float]
SVG = str


def _style2dict(s: str) -> dict[str, str]:
    return dict([e.split(":") for e in s.split(";")]) if s else {}


def _dict2style(s: Mapping[str, str]) -> str:
    return ";".join(["%s:%s" % i for i in s.items()])


def shaded_svg(
    mol,
    atom_shading: AtomShading | None = None,
    bond_shading: BondShading | None = None,
    **kwargs,
):
    """
    Functional interface to shade a molecule.

    This is a simple functional interface to shading. More complex
    depictions should work directly with  :class:`.Xenopict`.

    >>> import rdkit.Chem
    >>> diclofenac = mol = rdkit.Chem.MolFromSmiles('O=C(O)Cc1ccccc1Nc1c(Cl)cccc1Cl')

    >>> rdkit.Chem.rdPartialCharges.ComputeGasteigerCharges(mol)
    >>> shading = np.array([a.GetDoubleProp("_GasteigerCharge")  for a in mol.GetAtoms()])
    >>> shading = shading / abs(shading).max()  # partial charge (scaled to [-1, 1])

    >>> shaded_svg(mol, shading))
    ...

    Args:
        mol (RDKMol):
            Rdkit molecule,
        atom_shading (AtomShading | None, optional):
            Sequence of floats [-1,1] corresopnding to atom shades. Defaults to None.
        bond_shading (BondShading | None, optional):
            Sequence of floats [-1,1]. Defaults to None.

    Returns:
        SVG: SVG of the drawing.
    """

    drawer = Xenopict(mol, **kwargs)
    drawer.shade(atom_shading, bond_shading)
    return str(drawer)


class Xenopict:
    """
    This class draws an RDK molecule with sensible defaults,
    cleaning up the output SVG for easier modification and
    reduced size.

    >>> diclofenac = mol = Chem.MolFromSmiles('O=C(O)Cc1ccccc1Nc1c(Cl)cccc1Cl')
    >>> rdkit.Chem.rdPartialCharges.ComputeGasteigerCharges(mol)
    ...

    Partial charge (scaled to be in [-1, 1])

    >>> shading = np.array([a.GetDoubleProp("_GasteigerCharge")  for a in mol.GetAtoms()])
    >>> shading = shading / abs(shading).max()

    SVG of molecule shaded by partial charge,

    >>> drawer = class Xenopict(mol)
    >>> drawer.shade(shading)
    >>> str(drawer)
    ...

    Atoms can also be annotated with a circle,

    >>> drawer.mark([1, 2])

    The underlying svg dom (xml.dom.minidom) is accessible:

    >>> drawer.svgdom
    ...
    """

    down_scale = 0.7
    mark_down_scale = 1.0
    shapely_resolution = 6

    def __init__(
        self,
        input_mol: str | Mol | Xenopict,
        cmap: str | Colormap = "xenosite",
        plot_dot: PlotDot = PlotDot(),
        scale: float = 20,
        compute_coords=False,
        diverging_cmap=True,
    ):  # sourcery skip: use-dict-items
        if isinstance(input_mol, Mol):
            mol: Mol = input_mol
        elif isinstance(input_mol, str):
            mol: Mol = MolFromSmiles(input_mol)
        elif isinstance(input_mol, Xenopict):
            mol: Mol = input_mol.mol
        else:
            raise ValueError("Input must be RDMol or smiles string.")

        self.plot_dot = plot_dot
        self.mol: Mol = mol
        self.scale = scale

        self.diverging_cmap = diverging_cmap
        self._filter = None
        self._cmap: Colormap = cmap if isinstance(cmap, Colormap) else get_cmap(cmap)

        self.d2d = d2d = rdMolDraw2D.MolDraw2DSVG(-1, -1)

        rdDepictor.SetPreferCoordGen(False)
        d2d.drawOptions().fixedBondLength = self.scale
        d2d.drawOptions().padding = 0.1
        d2d.drawOptions().useBWAtomPalette()

        if compute_coords:
            rdDepictor.Compute2DCoords(mol)

        d2d.DrawMolecule(mol)
        self.coords = np.array(
            [tuple(d2d.GetDrawCoords(i)) for i in range(mol.GetNumAtoms())]
        )
        d2d.FinishDrawing()

        svg = d2d.GetDrawingText()
        self.svgdom = dom = parseString(str(svg))

        groups = ["shading", "mol_halo", "lines", "text", "overlay"]
        self.groups = {}
        for g in groups:
            self.groups[g] = dom.createElementNS("http://www.w3.org/2000/svg", "g")
            self.groups[g].setAttribute("class", g)

        for c in list(dom.childNodes[0].childNodes):
            if c.nodeName == "rect":
                dom.childNodes[0].removeChild(c)
                continue

            dom.childNodes[0].removeChild(c)

            if c.nodeName == "path":
                with contextlib.suppress(Exception):
                    c.removeAttribute("fill")

                if c.getAttribute("style"):
                    s = _style2dict(c.getAttribute("style"))
                    c.removeAttribute("style")

                    with contextlib.suppress(Exception):
                        del s["stroke-linecap"]
                        del s["stroke-linejoin"]
                        if s["fill"] == "none":
                            del s["fill"]

                    self.groups["lines"].setAttribute("style", _dict2style(s))
                    self.groups["lines"].appendChild(c)
                else:
                    self.groups["text"].appendChild(c)
            elif not c.TEXT_NODE:
                self.groups["text"].appendChild(c)

        s = self.groups["lines"].getAttribute("style")
        s = _style2dict(s)
        s["stroke-linecap"] = "round"
        s["stroke-linejoin"] = "round"
        s["stroke-width"] = str(1)
        self.groups["lines"].setAttribute("style", _dict2style(s))

        for g in self.groups:
            self.svgdom.firstChild.appendChild(self.groups[g])

        self.reframe()

    def copy(self):
        return Xenopict(self.mol)

    def color_map(self, color):
        if self.diverging_cmap:
            color = (color + 1.0) / 2
        return self._cmap(color)  # type: ignore

    def _shapely_from_atoms(self, atoms):
        atom_set = set(atoms)

        out = LineString()  # empty set

        for a in atoms:
            xy = self.coords[a]
            out = out.union(Point(*xy))

        for b in self.mol.GetBonds():
            a1 = b.GetBeginAtomIdx()
            a2 = b.GetEndAtomIdx()
            if a1 in atom_set and a2 in atom_set:
                c1 = self.coords[a1]
                c2 = self.coords[a2]
                out = out.union(LineString([c1, c2]))

        return out

    def mark_substructure(self, atoms: Sequence[AtomIdx]) -> Xenopict:
        if not atoms:
            return self

        substr = self._shapely_from_atoms(atoms).buffer(
            self.scale * self.mark_down_scale, resolution=self.shapely_resolution
        )
        d = _poly_to_path(substr)

        mark = self.svgdom.createElementNS("http://www.w3.org/2000/svg", "path")
        mark.setAttribute("d", d)
        self._append_mark(mark)
        return self

    def _append_mark(self, mark):
        self._init_mark_layers()
        self.groups["mark"].appendChild(mark)
        self.groups["halo"].appendChild(mark.cloneNode(True))

    def shade_substructure(
        self, substrs: Sequence[Sequence[AtomIdx]], shading: Sequence[float]
    ) -> Xenopict:
        dots = self.plot_dot.all_dots(shading)
        shapes = []

        for atoms, dot in zip(substrs, dots):
            if not atoms:
                continue
            substr = self._shapely_from_atoms(atoms)
            shapes.extend((radius, color, substr) for radius, color in dot)

        self.plot_dot._sort_dots(shapes)

        for radius, color, substr in shapes:
            color = self.color_map(color)
            fill = self._color_to_style(color)
            d = _poly_to_path(
                substr.buffer(
                    self.scale * radius * 0.9, resolution=self.shapely_resolution
                )
            )

            shade = self.svgdom.createElementNS("http://www.w3.org/2000/svg", "path")
            shade.setAttribute("d", d)
            shade.setAttribute("style", f"fill:{fill}")
            self.groups["shading"].appendChild(shade)

        return self

    def _color_to_style(self, color: Sequence[float]):
        return "rgb(%g,%g,%g)" % tuple(int(x * 255) for x in color[:3])

    def mark_atoms(self, atoms: Sequence[AtomIdx]) -> Xenopict:
        def marks():
            for a in atoms:
                xy = self.coords[a]
                circle = self._circle(
                    xy, self.scale * self.mark_down_scale, cls=f"atom-{a}"
                )
                yield circle

        for mark in marks():
            self._append_mark(mark)

        return self

    def shade(
        self,
        atom_shading: AtomShading | None = None,
        bond_shading: BondShading | None = None,
    ) -> Xenopict:
        scaling = self.scale * 0.9

        if atom_shading is not None and bond_shading is not None:
            scaling = self.scale * 0.8

        circles = []
        if atom_shading is not None:
            circles.extend(self.plot_dot(atom_shading, self.coords))

        if bond_shading is not None:
            atom1 = bond_shading[0]
            atom2 = bond_shading[1]
            bond_coords = (
                np.take(self.coords, atom1, axis=0)
                + np.take(self.coords, atom2, axis=0)
            ) / 2
            circles.extend(self.plot_dot(bond_shading[2], bond_coords))

        self.plot_dot._sort_dots(circles)

        for radius, color, xy in circles:
            c = self._circle(xy, radius * scaling, self.color_map(color))
            self.groups["shading"].appendChild(c)

        return self

    def _frame(self, padding=1.5, atoms=None):
        coords = self.coords

        if atoms is not None:
            coords = coords[atoms]
        elif self._filter:
            coords = coords[self._filter]

        xy1, xy2 = coords.min(axis=0), coords.max(axis=0)
        wh = xy2 - xy1 + self.scale * padding * 2
        xy1 = xy1 - self.scale * padding
        return xy1[0], xy1[1], wh[0], wh[1]

    def reframe(self, padding=1.5, atoms=None) -> Xenopict:
        x, y, w, h = self._frame(padding, atoms)
        self.svgdom.firstChild.setAttribute(
            "viewBox",
            "%0.1f %0.1f %0.1f %0.1f" % (x, y, w, h),
        )
        self.svgdom.firstChild.setAttribute("width", "%0.1f" % w)
        self.svgdom.firstChild.setAttribute("height", "%0.1f" % h)
        return self

    def __str__(self) -> SVG:
        return self.to_html()

    def __ge__(self, other: Xenopict | Mol | str):
        if isinstance(other, Xenopict):
            patt: Mol = other.mol
        elif isinstance(other, str):
            patt: Mol = MolFromSmarts(other)
        else:
            patt = other

        hit_ats = self.mol.GetSubstructMatch(patt)

        if not hit_ats:
            return False

        self.mark_substructure(hit_ats)
        return True

    def _repr_svg_(self):
        return self.to_svg()

    def to_svg(self):
        return self.svgdom.toxml()

    def to_html(self):
        datauri = f"data:image/svg+xml;utf8,{quote(self.to_svg())}"
        return f"<div style='background:white;width:100%'><img style='display:block;max-width:100%;margin:auto' data-xenopict src={datauri} /></div>"

    def __getattr__(self, key):
        """
        Look up missing members by aliasing to self.mol.
        """
        return self.__dict__[key] if key in self.__dict__ else getattr(self.mol, key)

    def halo(self) -> Xenopict:
        lines = self.groups["lines"].cloneNode(True)
        text = self.groups["text"].cloneNode(True)

        self.groups["mol_halo"].appendChild(lines)
        self.groups["mol_halo"].appendChild(text)

        self.groups["mol_halo"].setAttribute(
            "style",
            "stroke:white;opacity:0.5;stroke-linecap:round;stroke-linejoin:round",
        )

        lines.setAttribute("style", "stroke-width:3")
        text.setAttribute("style", "stroke-width:2")

        return self

    def _circle(
        self,
        xy: Sequence[float],
        radius: float,
        fill: Sequence[float] | None = None,
        stroke: Sequence[float] | None = None,
        style: dict[str, str] | None = None,
        cls: str | None = None,
    ):
        c = self.svgdom.createElementNS("http://www.w3.org/2000/svg", "circle")
        c.setAttribute("r", "%.1f" % (radius))
        c.setAttribute("cx", "%.1f" % xy[0])
        c.setAttribute("cy", "%.1f" % xy[1])

        style = style or {}
        if fill is not None:
            style["fill"] = self._color_to_style(fill)
        if stroke is not None:
            style["stroke"] = self._color_to_style(stroke)
        if style:
            c.setAttribute("style", _dict2style(style))
        if cls:
            c.setAttribute("class", cls)

        return c

    def filter(self, atoms: Sequence[AtomIdx]) -> Xenopict:
        atom_set = set(atoms)

        elems = list(self.groups["lines"].childNodes)
        elems += list(self.groups["text"].childNodes)

        for elem in elems:
            cls = set(elem.getAttribute("class").split())
            cls = {int(c.split("-")[1]) for c in cls if c.startswith("atom-")}

            if len(atom_set & cls) != len(cls):
                elem.parentNode.removeChild(elem)

        self._filter = atoms

        return self

    def substructure_focus(self, atoms: Sequence[AtomIdx]) -> Xenopict:
        if not atoms:
            return self

        self.filter(atoms)
        self.reframe()
        return self

    def _init_mark_layers(self):
        if "mark" in self.groups:
            return

        self.groups["halo"] = h = self.svgdom.createElementNS(
            "http://www.w3.org/2000/svg", "g"
        )
        h.setAttribute("class", "halo")
        h.setAttribute("stroke", "#555")
        h.setAttribute("opacity", "0.45")
        h.setAttribute("style", "fill:none;stroke-width:4")

        self.groups["mark"] = m = self.svgdom.createElementNS(
            "http://www.w3.org/2000/svg", "g"
        )
        m.setAttribute("class", "mark")
        m.setAttribute("stroke", "white")
        m.setAttribute("style", "fill:none;stroke-width:2;opacity:0.7")

        self.groups["overlay"].appendChild(h)
        self.groups["overlay"].appendChild(m)


def _poly_to_path(shape):
    d = ""
    if hasattr(shape.boundary, "geoms"):
        bounds = shape.boundary.geoms
    else:
        bounds = [shape.boundary]

    for s in bounds:
        XY = s.coords
        d += "M %0.1f,%0.1f " % XY[0]
        for xy in XY[1:]:
            d += "L %0.1f,%0.1f " % xy
        d += "Z "
    return d


def load_ipython_extension(ipython):
    import xenopict.magic
