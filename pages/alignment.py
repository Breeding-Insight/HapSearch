"""Alignment Tool - Multiple Sequence Alignment with CLUSTAL

Interactive MSA viewer with JalviewJS editing capabilities
"""

import dash
from dash import dcc, html, Input, Output, State, dash_table, no_update
import dash_bootstrap_components as dbc
from Bio import SeqIO
import pandas as pd
import base64
import io
import sys
import os
import plotly.graph_objects as go
import numpy as np

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import app for callback registration
from dash_app import app

from alignment.aligner import MSAAligner
from alignment.variant_annotator import VariantAnnotator
from design.colors import NUCLEOTIDE_COLORS


def create_alignment_heatmap(alignment_data):
    """Create MSA visualization as Plotly heatmap using custom nucleotide colors"""
    if not alignment_data:
        return go.Figure()

    # Extract sequences and labels
    sequences = [record['sequence'] for record in alignment_data]
    labels = [record['label'] for record in alignment_data]

    # Find the maximum sequence length
    seq_length = max(len(seq) for seq in sequences)

    # Enhanced color mapping for bases
    base_to_num = {'A': 0, 'T': 1, 'G': 2, 'C': 3, '-': 4, 'N': 5}
    matrix = []
    text_matrix = []

    # Create matrix for heatmap
    for seq in sequences:
        row = []
        text_row = []
        for i in range(seq_length):
            if i < len(seq):
                base = seq[i].upper()
                row.append(base_to_num.get(base, 5))
                text_row.append(base)
            else:
                # Pad with gap character
                row.append(4)
                text_row.append('-')
        matrix.append(row)
        text_matrix.append(text_row)

    matrix = np.array(matrix)

    # Create a discrete colorscale using exact value boundaries
    colorscale = []
    for i in range(6):
        start = i / 5.0
        end = (i + 0.99999) / 5.0
        color = [NUCLEOTIDE_COLORS['A'], NUCLEOTIDE_COLORS['T'],
                 NUCLEOTIDE_COLORS['G'], NUCLEOTIDE_COLORS['C'],
                 NUCLEOTIDE_COLORS['-'], NUCLEOTIDE_COLORS['N']][i]
        colorscale.append([start, color])
        if i < 5:
            colorscale.append([end, color])

    # Create heatmap with nucleotide colors
    fig = go.Figure(data=go.Heatmap(
        z=matrix,
        x=list(range(1, seq_length + 1)),
        y=labels,
        colorscale=colorscale,
        zmin=0,
        zmax=5,
        showscale=False,
        text=text_matrix,
        texttemplate='%{text}',
        textfont={"size": 12, "family": "Courier New, monospace", "color": "black"},
        hovertemplate='<b>Position:</b> %{x}<br><b>Sequence:</b> %{y}<br><b>Base:</b> %{text}<extra></extra>',
        xgap=0.5,
        ygap=0.5
    ))

    # Update layout for clean appearance
    fig.update_layout(
        xaxis=dict(
            title="Position",
            side="top",
            tickmode='linear',
            tick0=1,
            dtick=5,
            showgrid=False
        ),
        yaxis=dict(
            title="",
            showgrid=False,
            autorange='reversed'
        ),
        plot_bgcolor='#f5f5f5',  # Light gray background to make white gaps visible
        paper_bgcolor='white',
        margin=dict(l=150, r=20, t=80, b=40),
        height=max(300, len(sequences) * 30),
        font=dict(size=11)
    )

    return fig


# Layout
layout = dbc.Container([
    dcc.Store(id='alignment-data-store'),
    dcc.Store(id='variant-data-store'),
    dcc.Store(id='upload-filename-store'),

    html.H2([
        html.I(className="fas fa-align-left me-2"),
        "Multiple Sequence Alignment"
    ], className="mb-1"),
    html.P("Align sequences using CLUSTAL Omega, detect variants, and edit alignments",
           className="text-muted mb-4"),

    dbc.Row([
        # Left panel: Controls
        dbc.Col([
            # Upload sequences
            dbc.Card([
                dbc.CardHeader(html.H5([
                    html.I(className="fas fa-upload me-2"),
                    "1. Upload Sequences"
                ], className="mb-0")),
                dbc.CardBody([
                    dcc.Upload(
                        id='upload-sequences',
                        children=html.Div([
                            html.I(className="fas fa-cloud-upload-alt fa-2x mb-2"),
                            html.Br(),
                            'Drag and Drop or ',
                            html.A('Select FASTA File', className="text-primary fw-bold")
                        ]),
                        style={
                            'width': '100%',
                            'height': '100px',
                            'lineHeight': '30px',
                            'borderWidth': '2px',
                            'borderStyle': 'dashed',
                            'borderRadius': '8px',
                            'textAlign': 'center',
                            'padding': '20px',
                            'cursor': 'pointer',
                            'backgroundColor': '#f8f9fa'
                        },
                        multiple=False
                    ),
                    html.Div(id='upload-status', className="mt-2 small")
                ])
            ], className="mb-3"),

            # Run Alignment
            dbc.Card([
                dbc.CardHeader(html.H5([
                    html.I(className="fas fa-cogs me-2"),
                    "2. Run Alignment"
                ], className="mb-0")),
                dbc.CardBody([
                    html.Div([
                        html.Small([
                            html.I(className="fas fa-info-circle me-1"),
                            "Using CLUSTAL Omega for progressive alignment"
                        ], className="text-muted mb-3 d-block")
                    ]),
                    dbc.Button(
                        [html.I(className="fas fa-play me-2"), "Run Alignment"],
                        id='run-alignment-btn',
                        color='primary',
                        className="w-100",
                        size="lg"
                    ),
                    dcc.Loading(
                        id='loading-alignment',
                        children=html.Div(id='alignment-status'),
                        type='default'
                    )
                ])
            ], className="mb-3"),

            # Variant detection
            dbc.Card([
                dbc.CardHeader(html.H5([
                    html.I(className="fas fa-dna me-2"),
                    "3. Detect Variants"
                ], className="mb-0")),
                dbc.CardBody([
                    html.Label("Minimum Allele Frequency:", className="fw-bold small mb-2"),
                    dcc.Slider(
                        id='min-frequency-slider',
                        min=0,
                        max=0.5,
                        step=0.05,
                        value=0.1,
                        marks={i/10: f'{int(i*10)}%' for i in range(6)},
                        tooltip={"placement": "bottom", "always_visible": True}
                    ),
                    dbc.Button(
                        [html.I(className="fas fa-search me-2"), "Detect Variants"],
                        id='detect-variants-btn',
                        color='success',
                        className="w-100 mt-3"
                    ),
                    html.Div(id='variant-status', className="mt-2")
                ])
            ], className="mb-3"),

            # Export options
            dbc.Card([
                dbc.CardHeader(html.H5([
                    html.I(className="fas fa-download me-2"),
                    "Export"
                ], className="mb-0")),
                dbc.CardBody([
                    dbc.Button(
                        [html.I(className="fas fa-file-alt me-2"), "Download FASTA"],
                        id='download-fasta-btn',
                        color='secondary',
                        outline=True,
                        className="w-100 mb-2",
                        size="sm"
                    ),
                    dbc.Button(
                        [html.I(className="fas fa-file-code me-2"), "Download VCF"],
                        id='download-vcf-btn',
                        color='secondary',
                        outline=True,
                        className="w-100",
                        size="sm"
                    ),
                    dcc.Download(id='download-fasta'),
                    dcc.Download(id='download-vcf')
                ])
            ])
        ], width=3),

        # Right panel: Visualization
        dbc.Col([
            # Tabs for different views
            dbc.Tabs([
                # Alignment viewer tab
                dbc.Tab([
                    dcc.Loading(
                        html.Div(id='alignment-viewer-container', className="mt-3"),
                        type='default'
                    )
                ], label="Alignment Viewer", tab_id="viewer-tab",
                   label_style={"color": "#495057"},
                   active_label_style={"color": "#245842"}),

                # JalviewJS editor tab
                dbc.Tab([
                    html.Div([
                        dbc.Alert([
                            html.I(className="fas fa-info-circle me-2"),
                            "Use JalviewJS to manually edit alignments. ",
                            html.Strong("Note:"),
                            " Changes made here are not automatically synced back. ",
                            "Export your edited alignment and re-upload if needed."
                        ], color="info", className="mt-3"),

                        html.Iframe(
                            id='jalview-iframe',
                            src='https://www.jalview.org/jalview-js/JalviewJS/',
                            style={
                                'width': '100%',
                                'height': '700px',
                                'border': '1px solid #ddd',
                                'borderRadius': '5px',
                                'marginTop': '10px'
                            }
                        ),

                        dbc.Card([
                            dbc.CardBody([
                                html.H6("How to use JalviewJS:", className="mb-3"),
                                html.Ol([
                                    html.Li("Download your alignment using the 'Download FASTA' button"),
                                    html.Li("In JalviewJS above, click 'Open' and upload the downloaded file"),
                                    html.Li("Edit alignment manually (insert/delete gaps, move sequences)"),
                                    html.Li("Export edited alignment from JalviewJS (File → Export)"),
                                    html.Li("Re-upload the edited file to continue analysis")
                                ], className="small")
                            ])
                        ], className="mt-3")
                    ])
                ], label="Edit in JalviewJS", tab_id="jalview-tab",
                   label_style={"color": "#495057"},
                   active_label_style={"color": "#245842"}),

                # Variant analysis tab
                dbc.Tab([
                    html.Div(id='variant-analysis-container', className="mt-3")
                ], label="Variant Analysis", tab_id="variants-tab",
                   label_style={"color": "#495057"},
                   active_label_style={"color": "#245842"})
            ], id="main-tabs", active_tab="viewer-tab")
        ], width=9)
    ])

], fluid=True)


# Upload callback
@app.callback(
    [Output('upload-status', 'children'),
     Output('upload-filename-store', 'data')],
    Input('upload-sequences', 'contents'),
    State('upload-sequences', 'filename')
)
def process_upload(contents, filename):
    """Process uploaded FASTA file"""
    if not contents:
        return "", None

    try:
        # Parse uploaded file
        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)
        sequences = list(SeqIO.parse(io.StringIO(decoded.decode('utf-8')), "fasta"))

        if len(sequences) < 2:
            return dbc.Alert(
                "At least 2 sequences required for alignment",
                color="danger",
                className="mb-0"
            ), None

        return dbc.Alert([
            html.I(className="fas fa-check-circle me-2"),
            f"Loaded {len(sequences)} sequences from {filename}"
        ], color="success", className="mb-0"), filename

    except Exception as e:
        return dbc.Alert(
            f"Error reading file: {str(e)}",
            color="danger",
            className="mb-0"
        ), None


# Alignment callback
@app.callback(
    [Output('alignment-data-store', 'data'),
     Output('alignment-status', 'children')],
    Input('run-alignment-btn', 'n_clicks'),
    State('upload-sequences', 'contents'),
    prevent_initial_call=True
)
def run_alignment(n_clicks, file_contents):
    """Run MSA alignment using CLUSTAL Omega"""
    if not file_contents:
        return None, dbc.Alert("Please upload sequences first", color="warning")

    try:
        # Parse uploaded file
        content_type, content_string = file_contents.split(',')
        decoded = base64.b64decode(content_string)
        sequences = list(SeqIO.parse(io.StringIO(decoded.decode('utf-8')), "fasta"))

        # Run alignment with CLUSTAL
        aligner = MSAAligner(algorithm='clustal')
        alignment = aligner.align_sequences(sequences)

        # Convert to dictionary format
        alignment_data = aligner.alignment_to_dict(alignment)

        # Store FASTA format as well
        fasta_content = aligner.alignment_to_fasta(alignment)

        return {
            'alignment': alignment_data,
            'fasta': fasta_content,
            'algorithm': 'clustal'
        }, dbc.Alert([
            html.I(className="fas fa-check-circle me-2"),
            "Alignment complete using CLUSTAL Omega"
        ], color="success", className="mt-2")

    except Exception as e:
        return None, dbc.Alert(
            f"Alignment failed: {str(e)}",
            color="danger",
            className="mt-2"
        )


# Visualization callback
@app.callback(
    Output('alignment-viewer-container', 'children'),
    Input('alignment-data-store', 'data')
)
def display_alignment(alignment_store):
    """Display alignment using Dash Bio"""
    if not alignment_store or 'alignment' not in alignment_store:
        return dbc.Alert(
            "Upload sequences and run alignment to view results",
            color="info",
            className="text-center"
        )

    try:
        # Get alignment data
        alignment_data = alignment_store['alignment']

        if not alignment_data:
            return dbc.Alert(
                "Invalid alignment data format",
                color="danger"
            )

        # Create custom heatmap visualization
        fig = create_alignment_heatmap(alignment_data)

        # Create color legend
        color_legend = html.Div([
            html.Span("Color Legend (Purines: A/G, Pyrimidines: C/T): ", className="me-2", style={'fontWeight': 'bold'}),
            html.Span([
                html.Span("A", style={
                    'backgroundColor': NUCLEOTIDE_COLORS['A'],
                    'color': 'white',
                    'padding': '3px 10px',
                    'marginRight': '8px',
                    'fontFamily': 'Courier New, monospace',
                    'fontWeight': 'bold',
                    'borderRadius': '3px',
                    'border': '1px solid #ddd'
                }),
                html.Span("G", style={
                    'backgroundColor': NUCLEOTIDE_COLORS['G'],
                    'color': 'black',
                    'padding': '3px 10px',
                    'marginRight': '15px',
                    'fontFamily': 'Courier New, monospace',
                    'fontWeight': 'bold',
                    'borderRadius': '3px',
                    'border': '1px solid #ddd'
                }),
                html.Span("C", style={
                    'backgroundColor': NUCLEOTIDE_COLORS['C'],
                    'color': 'white',
                    'padding': '3px 10px',
                    'marginRight': '8px',
                    'fontFamily': 'Courier New, monospace',
                    'fontWeight': 'bold',
                    'borderRadius': '3px',
                    'border': '1px solid #ddd'
                }),
                html.Span("T", style={
                    'backgroundColor': NUCLEOTIDE_COLORS['T'],
                    'color': 'white',
                    'padding': '3px 10px',
                    'marginRight': '15px',
                    'fontFamily': 'Courier New, monospace',
                    'fontWeight': 'bold',
                    'borderRadius': '3px',
                    'border': '1px solid #ddd'
                }),
                html.Span("-", style={
                    'backgroundColor': NUCLEOTIDE_COLORS['-'],
                    'color': 'black',
                    'padding': '3px 10px',
                    'fontFamily': 'Courier New, monospace',
                    'fontWeight': 'bold',
                    'borderRadius': '3px',
                    'border': '1px solid #999'
                }),
            ])
        ], className="mb-3", style={'fontSize': '0.95em'})

        return dbc.Card([
            dbc.CardHeader([
                html.H5([
                    html.I(className="fas fa-dna me-2"),
                    f"Alignment Visualization ({len(alignment_data)} sequences)"
                ], className="mb-0 d-inline-block"),
            ]),
            dbc.CardBody([
                color_legend,
                dcc.Graph(
                    id='alignment-chart',
                    figure=fig,
                    config={
                        'displayModeBar': True,
                        'displaylogo': False,
                        'modeBarButtonsToRemove': ['pan2d', 'lasso2d', 'select2d'],
                        'toImageButtonOptions': {
                            'format': 'png',
                            'filename': 'alignment',
                            'height': None,
                            'width': None,
                        }
                    }
                )
            ], style={'overflowX': 'auto'})
        ])
    except Exception as e:
        return dbc.Alert(
            f"Error displaying alignment: {str(e)}",
            color="danger"
        )


# Variant detection callback
@app.callback(
    [Output('variant-data-store', 'data'),
     Output('variant-status', 'children')],
    Input('detect-variants-btn', 'n_clicks'),
    [State('alignment-data-store', 'data'),
     State('min-frequency-slider', 'value')],
    prevent_initial_call=True
)
def detect_variants(n_clicks, alignment_store, min_frequency):
    """Detect and annotate variants"""
    if not alignment_store or 'fasta' not in alignment_store:
        return None, dbc.Alert("Please run alignment first", color="warning")

    try:
        # Parse FASTA alignment
        from Bio import AlignIO
        fasta_content = alignment_store['fasta']
        alignment = AlignIO.read(io.StringIO(fasta_content), "fasta")

        # Detect variants
        annotator = VariantAnnotator(min_frequency=min_frequency)
        variants = annotator.annotate_alignment(alignment)

        # Get summary
        summary = annotator.get_variant_summary(variants)

        return variants, dbc.Alert([
            html.I(className="fas fa-check-circle me-2"),
            f"Detected {summary['total_variants']} variants ",
            f"({summary['snps']} SNPs, {summary['indels']} indels)"
        ], color="success", className="mt-2")

    except Exception as e:
        return None, dbc.Alert(
            f"Variant detection failed: {str(e)}",
            color="danger",
            className="mt-2"
        )


# Variant analysis display
@app.callback(
    Output('variant-analysis-container', 'children'),
    Input('variant-data-store', 'data')
)
def display_variant_analysis(variants):
    """Display variant analysis results"""
    if not variants:
        return dbc.Alert(
            "Run variant detection to view analysis",
            color="info",
            className="text-center"
        )

    # Create annotator to get summary
    annotator = VariantAnnotator()
    summary = annotator.get_variant_summary(variants)
    df = annotator.export_variants_dataframe(variants)

    return html.Div([
        # Summary statistics
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H3(summary['total_variants'], className="mb-0 text-primary"),
                        html.Small("Total Variants", className="text-muted")
                    ], className="text-center")
                ])
            ], width=3),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H3(summary['snps'], className="mb-0 text-success"),
                        html.Small("SNPs", className="text-muted")
                    ], className="text-center")
                ])
            ], width=3),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H3(summary['indels'], className="mb-0 text-warning"),
                        html.Small("Indels", className="text-muted")
                    ], className="text-center")
                ])
            ], width=3),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H3(f"{summary['ti_tv_ratio']:.2f}", className="mb-0 text-info"),
                        html.Small("Ts/Tv Ratio", className="text-muted")
                    ], className="text-center")
                ])
            ], width=3)
        ], className="mb-4"),

        # Variant table
        dbc.Card([
            dbc.CardHeader(html.H5("Detected Variants", className="mb-0")),
            dbc.CardBody([
                dbc.Table.from_dataframe(
                    df,
                    striped=True,
                    bordered=True,
                    hover=True,
                    responsive=True,
                    size='sm'
                )
            ])
        ])
    ])


# Download FASTA
@app.callback(
    Output('download-fasta', 'data'),
    Input('download-fasta-btn', 'n_clicks'),
    [State('alignment-data-store', 'data'),
     State('upload-filename-store', 'data')],
    prevent_initial_call=True
)
def download_fasta(n_clicks, alignment_store, original_filename):
    """Download alignment as FASTA"""
    if not alignment_store or 'fasta' not in alignment_store:
        return no_update

    fasta_content = alignment_store['fasta']
    filename = f"{original_filename.rsplit('.', 1)[0]}_aligned.fasta" if original_filename else "alignment.fasta"

    return dict(content=fasta_content, filename=filename)


# Download VCF
@app.callback(
    Output('download-vcf', 'data'),
    Input('download-vcf-btn', 'n_clicks'),
    [State('variant-data-store', 'data'),
     State('upload-filename-store', 'data')],
    prevent_initial_call=True
)
def download_vcf(n_clicks, variants, original_filename):
    """Download variants as VCF"""
    if not variants:
        return no_update

    # Create temp VCF file
    import tempfile
    annotator = VariantAnnotator()

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.vcf') as f:
        ref_id = original_filename.rsplit('.', 1)[0] if original_filename else "alignment"
        annotator.export_vcf(variants, ref_id, f.name)

        with open(f.name, 'r') as vcf_file:
            vcf_content = vcf_file.read()

        os.unlink(f.name)

    filename = f"{ref_id}_variants.vcf"
    return dict(content=vcf_content, filename=filename)
