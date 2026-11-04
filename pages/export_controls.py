"""Save controls shared by every chart and table download.

Each control shows the file name it is about to save under and lets the user
change it. assets/plot_export.js does the image saving in the browser.
"""

import re

from dash import html
import dash_bootstrap_components as dbc

# Characters Windows, macOS or Linux refuse in a file name, plus whitespace.
_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\s]+')


def clean_filename(name, fallback, extension=None):
    """Make a typed file name safe to save, without its extension.

    Drops a trailing ".<extension>" the user typed (the extension is added
    when saving) and replaces characters that file systems reject.
    """
    name = (name or '').strip()
    if extension and name.lower().endswith(f'.{extension.lower()}'):
        name = name[:-(len(extension) + 1)]
    name = _UNSAFE_FILENAME_CHARS.sub('_', name).strip('._')
    return name or fallback


def filename_field(input_id, value, extension, extension_id=None):
    """A "File name" box with the extension shown after it."""
    extension_props = {'id': extension_id} if extension_id else {}
    return html.Div(
        [
            html.Label("File name", htmlFor=input_id, className="fw-bold small mb-1"),
            dbc.InputGroup(
                [
                    dbc.Input(
                        id=input_id,
                        type='text',
                        value=value,
                        size='sm',
                        autoComplete='off',
                        className="save-filename-input",
                    ),
                    dbc.InputGroupText(f'.{extension}', className="save-filename-ext",
                                       **extension_props),
                ],
                size='sm',
            ),
        ],
        className="mb-3",
    )


def plot_export_controls(
    chart_key,
    graph_id,
    filename,
    default_width=10,
    default_height=6,
    class_name="d-flex justify-content-end mb-2",
):
    """A "Save" menu for a Plotly chart: file name, type, resolution and size.

    chart_key prefixes the controls' ids ("<chart_key>-image-type", ...).
    """
    return html.Div(
        [
            dbc.DropdownMenu(
                [
                    html.Div(
                        [
                            html.H6("Save Image", className="mb-3"),
                            filename_field(
                                f"{chart_key}-image-filename",
                                filename,
                                'png',
                                extension_id=f"{chart_key}-image-ext",
                            ),
                            html.Label("File type", className="fw-bold small mb-1"),
                            dbc.Select(
                                id=f"{chart_key}-image-type",
                                options=[
                                    {"label": "jpeg", "value": "jpeg"},
                                    {"label": "png", "value": "png"},
                                    {"label": "svg", "value": "svg"},
                                ],
                                value="png",
                                size="sm",
                                className="mb-3",
                            ),
                            html.Label("Resolution", className="fw-bold small mb-1"),
                            dbc.Input(
                                id=f"{chart_key}-image-res",
                                type="number",
                                value=300,
                                min=50,
                                max=1000,
                                step=50,
                                size="sm",
                                className="mb-3",
                            ),
                            html.Label("Width", className="fw-bold small mb-1"),
                            dbc.Input(
                                id=f"{chart_key}-image-width",
                                type="number",
                                value=default_width,
                                min=1,
                                max=20,
                                step=0.5,
                                size="sm",
                                className="mb-3",
                            ),
                            html.Label("Height", className="fw-bold small mb-1"),
                            dbc.Input(
                                id=f"{chart_key}-image-height",
                                type="number",
                                value=default_height,
                                min=1,
                                max=20,
                                step=0.5,
                                size="sm",
                                className="mb-3",
                            ),
                            html.Button(
                                [html.I(className="fas fa-download me-2"), "Save Image"],
                                id=f"{chart_key}-save-image-btn",
                                type="button",
                                className="btn btn-primary btn-sm w-100",
                                **{
                                    "data-export-chart": chart_key,
                                    "data-export-graph": graph_id,
                                    "data-export-filename": filename,
                                },
                            ),
                        ],
                        className="px-3 py-2",
                        style={"width": "300px"},
                    ),
                ],
                label=[html.I(className="fas fa-floppy-disk me-2"), "Save"],
                color="secondary",
                toggle_class_name="haplo-action-btn",
                size="sm",
                align_end=True,
                className="d-inline-block",
            ),
        ],
        className=class_name,
    )
