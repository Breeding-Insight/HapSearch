"""Marker Explorer - Split-view interface with comparison mode"""

import dash
from dash import dcc, html, Input, Output, State, no_update, ctx
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import numpy as np
from collections import Counter
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dash_app import app

from database.db_manager import DatabaseManager
from database.queries import (
    get_markers_paginated,
    get_marker_details,
    get_microhaplotypes_for_marker,
    get_variants_for_marker,
    get_all_chromosomes_for_species,
    get_botloci_count,
    is_bottom_locus
)
from design.colors import NUCLEOTIDE_COLORS
from alignment.coordinates import (
    MSA_AXIS_TICK_FONT,
    MSA_AXIS_TITLE_FONT,
    msa_chart_title,
    relative_position,
    relative_positions,
)
from alignment.aligner import MSAAligner
from alignment.variant_annotator import VariantAnnotator
from Bio.SeqRecord import SeqRecord
from Bio.Seq import Seq
from Bio.Align import MultipleSeqAlignment

def create_single_view_layout():
    return dbc.Row([
        dbc.Col([
            html.Div([
                dbc.Card([
                    dbc.CardHeader([
                        html.Div([
                            html.H5([
                                html.I(className="fas fa-search me-2", id='marker-search-icon'),
                                html.Span("Search & Browse", id='marker-search-title')
                            ], className="mb-0"),
                            dbc.Button(
                                html.I(className="fas fa-chevron-left", id='marker-minimize-icon'),
                                id='marker-minimize-btn',
                                color="link",
                                size="sm",
                                className="float-end p-0",
                                style={'color': '#000000', 'textDecoration': 'none'}
                            ),
                        ], style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center', 'width': '100%'})
                    ]),
                    dbc.CardBody([
                        html.Div([
                            html.Label("Chromosome:", className="fw-bold small", id='marker-chromosome-label'),
                            dcc.Dropdown(
                                id='marker-chromosome-filter',
                                placeholder="All chromosomes",
                                clearable=True,
                                searchable=True,
                                className="mb-3"
                            )
                        ], id='marker-chromosome-container'),

                        html.Div([
                            html.Label("Allele ID:", className="fw-bold small", id='marker-search-label'),
                            dbc.Input(
                                id='marker-search-input',
                                type='text',
                                placeholder='Search allele ID...',
                                debounce=True,
                                className="mb-3"
                            )
                        ], id='marker-search-container'),

                        html.Div([
                            html.Label("Sequence:", className="fw-bold small", id='marker-sequence-search-label'),
                            dbc.Input(
                                id='marker-sequence-search-input',
                                type='text',
                                placeholder='Search sequence...',
                                debounce=True,
                                className="mb-2"
                            )
                        ], id='marker-sequence-search-container')
                    ], id='marker-filters-body')
                ], style={'flexShrink': '0'}, className="mb-2", id='marker-filters-card'),

                dbc.Card([
                    dbc.CardBody([
                        html.Label("Results:", className="fw-bold small mb-2", id='marker-results-label'),
                        html.Div(id='marker-search-results'),
                        html.Div([
                            html.Div(id='marker-pagination-info', className="me-3 text-muted small align-self-center"),
                            dbc.Button(
                                html.I(className="fas fa-chevron-left"),
                                id='marker-page-prev',
                                color="secondary",
                                outline=True,
                                size="sm",
                                className="me-2 haplo-action-btn"
                            ),
                            html.Span(id='marker-page-indicator', className="text-muted small align-self-center me-2"),
                            dbc.Button(
                                html.I(className="fas fa-chevron-right"),
                                id='marker-page-next',
                                color="secondary",
                                outline=True,
                                size="sm",
                                className="haplo-action-btn"
                            )
                        ], className="mt-2 d-flex justify-content-center align-items-center", id='marker-pagination-container')
                    ])
                ], id='marker-results-card')
            ], style={'display': 'flex', 'flexDirection': 'column'}, id='marker-left-panel-content')
        ], id='marker-left-col', width=3),

        dbc.Col([
            dbc.Card([
                dbc.CardHeader(html.H5([
                    html.I(className="fas fa-info-circle me-2"),
                    "Locus Details"
                ])),
                dbc.CardBody([
                    html.Div(id='marker-detail-panel')
                ])
            ])
        ], id='marker-right-col', width=9)
    ])


# Layout - calls the function after it's defined
layout = dbc.Container([
    dcc.Store(id='marker-detail-store', data=None),
    dcc.Store(
        id='marker-alignment-store',
        data={'status': 'original', 'marker_id': None, 'sequences': None, 'variants': None}
    ),
    dcc.Store(id='marker-left-panel-minimized', data=False),
    dcc.Store(id='marker-results-page', data=1),

    create_single_view_layout()

], fluid=True)


@app.callback(
    Output('marker-chromosome-filter', 'options'),
    Input('selected-species-store', 'data')
)
def load_chromosomes(species_id):
    """Load chromosomes for selected species"""
    if not species_id:
        return []

    try:
        db = DatabaseManager()
        with db.shared_connection():
            chromosomes = get_all_chromosomes_for_species(db, species_id)
        return [{'label': c['chromosome_name'], 'value': c['id']} for c in chromosomes]
    except Exception:
        return []




@app.callback(
    [Output('marker-results-page', 'data'),
     Output('marker-page-indicator', 'children'),
     Output('marker-page-prev', 'disabled'),
     Output('marker-page-next', 'disabled'),
     Output('marker-pagination-container', 'style'),
     Output('marker-pagination-info', 'children')],
    Input('marker-search-input', 'value'),
    Input('marker-sequence-search-input', 'value'),
    Input('selected-species-store', 'data'),
    Input('marker-chromosome-filter', 'value'),
    Input('marker-page-prev', 'n_clicks'),
    Input('marker-page-next', 'n_clicks'),
    State('marker-results-page', 'data'),
    prevent_initial_call=True
)
def update_marker_page(search_term, sequence_search, species_id, chromosome_id, prev_clicks, next_clicks, current_page):
    """Update page number based on filters or pagination component"""
    triggered = ctx.triggered_id if ctx.triggered else None
    
    # Get total pages and total count for pagination
    try:
        db = DatabaseManager()
        with db.shared_connection():
            result = get_markers_paginated(
                db,
                species_id=species_id,
                chromosome_id=chromosome_id,
                search_marker_id=search_term,
                search_sequence=sequence_search,
                page=1,
                per_page=7
            )
            total_pages = result.get('total_pages', 1)
            total_count = result.get('total', 0)
    except Exception:
        total_pages = 1
        total_count = 0
    
    # Create pagination info text
    if total_count > 0:
        pagination_info = f"{total_count:,} Loci"
    else:
        pagination_info = ""
    
    # Determine new page
    page = current_page or 1

    # Reset to page 1 when filters change
    if triggered in ['marker-search-input', 'marker-sequence-search-input', 'selected-species-store', 'marker-chromosome-filter']:
        page = 1
    elif triggered == 'marker-page-prev':
        page = max(1, page - 1)
    elif triggered == 'marker-page-next':
        page = min(total_pages, page + 1)

    # Clamp page in case total_pages shrank
    page = max(1, min(page, total_pages))

    show_controls = total_pages > 1 and total_count > 0
    container_style = {'display': 'flex'} if show_controls else {'display': 'none'}
    info_style = {'display': 'block'} if total_count > 0 else {'display': 'none'}

    indicator = f"Page {page} of {total_pages}" if show_controls else ""
    prev_disabled = page <= 1
    next_disabled = page >= total_pages

    return page, indicator, prev_disabled, next_disabled, container_style, html.Span(pagination_info, style=info_style)


@app.callback(
    Output('marker-search-results', 'children'),
    Input('marker-search-input', 'value'),
    Input('marker-sequence-search-input', 'value'),
    Input('selected-species-store', 'data'),
    Input('marker-chromosome-filter', 'value'),
    Input('marker-results-page', 'data'),
    prevent_initial_call=True
)
def search_markers(search_term, sequence_search, species_id, chromosome_id, current_page):
    """Search and display markers with pagination"""
    try:
        db = DatabaseManager()
        with db.shared_connection():
            result = get_markers_paginated(
                db,
                species_id=species_id,
                chromosome_id=chromosome_id,
                search_marker_id=search_term,
                search_sequence=sequence_search,
                page=current_page or 1,
                per_page=7
            )

        if not result['markers']:
            return html.Div("No markers found", className="text-muted small")

        marker_items = []
        for m in result['markers']:
            item = dbc.ListGroupItem([
                html.Div([
                    html.Strong(
                        m['marker_id'],
                        style={'display': 'block', 'lineHeight': '1.1', 'marginBottom': '0.15rem'}
                    ),
                    html.Small([
                        html.I(className="fas fa-dna me-1"),
                        f"{m['microhaplotype_count']} microhaplotypes"
                    ], className="text-muted", style={'display': 'block', 'lineHeight': '1.1'})
                ])
            ], action=True, id={'type': 'marker-list-item', 'index': m['marker_id']})
            marker_items.append(item)

        return html.Div([dbc.ListGroup(marker_items)])

    except Exception as e:
        return html.Div(f"Error: {str(e)}", className="text-danger small")


@app.callback(
    [Output('marker-detail-panel', 'children'),
     Output('marker-detail-store', 'data'),
     Output('navigate-to-marker-store', 'data', allow_duplicate=True)],
    Input({'type': 'marker-list-item', 'index': dash.ALL}, 'n_clicks'),
    Input('navigate-to-marker-store', 'data'),
    State('marker-detail-store', 'data'),
    prevent_initial_call=True
)
def show_marker_details(n_clicks, navigate_data, current_marker_id):
    """Display selected marker details"""
    marker_id = None

    triggered = ctx.triggered_id if ctx.triggered else None

    if triggered == 'navigate-to-marker-store':
        if navigate_data and isinstance(navigate_data, dict) and navigate_data.get('marker_id'):
            marker_id = navigate_data['marker_id']
            return create_marker_detail_view(marker_id), marker_id, no_update
    
    if triggered and isinstance(triggered, dict) and triggered.get('type') == 'marker-list-item':
        # Only update if there was an actual click (n_clicks changed)
        if n_clicks and any(clicks and clicks > 0 for clicks in n_clicks if clicks is not None):
            marker_id = triggered['index']
            return create_marker_detail_view(marker_id), marker_id, no_update
    
    # If no valid trigger, preserve current selection
    if current_marker_id:
        return no_update, no_update, no_update
    
    # Only show placeholder if no marker was ever selected
    empty_fig = go.Figure()
    empty_fig.update_layout(template='plotly_white', xaxis={'visible': False}, yaxis={'visible': False})
    placeholder_view = html.Div([
        html.Div("Select a locus result to view details", className="text-muted"),
        html.Div(id='alignment-status-message', style={'display': 'none'}),
        dbc.Button(
            [html.I(className="fas fa-undo me-2"), "Show Original (Unaligned)"],
            id='show-original-btn',
            className="haplo-action-btn",
            style={'display': 'none'}
        ),
        dcc.Graph(
            id='msa-graph',
            figure=empty_fig,
            config={'displayModeBar': False},
            style={'display': 'none'}
        )
        ])
    return placeholder_view, None, no_update


def create_marker_detail_view(marker_id):
    """Create detailed view of a marker"""
    if not marker_id:
        return html.Div("No marker selected", className="text-muted")

    try:
        db = DatabaseManager()
        with db.shared_connection():
            marker = get_marker_details(db, marker_id)

            if not marker:
                return html.Div("Marker not found", className="text-danger")

            haplotypes = get_microhaplotypes_for_marker(db, marker_id)
            variants = get_variants_for_marker(db, marker_id)

        haplotypes_sorted = sorted(haplotypes, key=lambda h: get_allele_sort_key(h['haplotype_name']), reverse=False)

        if not variants and haplotypes:
            variants = auto_detect_variants(haplotypes, marker)

        seq_length = len(haplotypes[0]['haplotype_sequence']) if haplotypes else 0

        if marker['position_end'] > marker['position_start']:
            bp_length = marker['position_end'] - marker['position_start']
        else:
            bp_length = seq_length
        loading_fig = go.Figure()
        loading_fig.update_layout(
            template='plotly_white',
            xaxis={'visible': False},
            yaxis={'visible': False},
            annotations=[{
                'text': 'Aligning sequences...',
                'xref': 'paper',
                'yref': 'paper',
                'x': 0.5,
                'y': 0.5,
                'showarrow': False,
                'font': {'size': 20, 'color': '#999'}
            }]
        )

        return html.Div([
            html.H5(marker['marker_id'], className="mb-1"),
            html.P([
                html.I(className="fas fa-map-marker-alt me-2"),
                f"{bp_length} bp"
            ], className="text-muted small mb-1"),
            html.P([
                html.I(className="fas fa-dna me-2"),
                f"{len(haplotypes)} microhaplotypes"
            ], className="text-muted small mb-3"),

            html.Hr(),
            html.Div([
                html.H6([
                    "Multiple Sequence Alignment"
                ], className="mb-2 d-inline-block"),
                dbc.Button(
                    [html.I(className="fas fa-undo me-2"), "Show Original (Unaligned)"],
                    id='show-original-btn',
                    color='secondary',
                    size='sm',
                    outline=True,
                    className="float-end haplo-action-btn"
                )
            ]),
            dcc.Loading(
                id='loading-alignment',
                children=html.Div(id='alignment-status-message', children=html.Div()),
                type='default'
            ),
            dcc.Graph(
                id='msa-graph',
                figure=loading_fig,
                config={'displayModeBar': True, 'displaylogo': False}
            ),

            html.Div([
                html.Small("Click microhaplotype ID to view details:", className="text-muted me-2"),
                html.Div([
                    dbc.Button(
                        h['haplotype_name'].split('|')[-1],  # Show just the allele ID
                        id={'type': 'haplotype-link-btn', 'index': h['haplotype_name']},
                        color="primary",
                        outline=True,
                        size="sm",
                        className="me-1 mb-1"
                    ) for h in haplotypes_sorted
                ], className="d-flex flex-wrap")
            ], className="mb-3 p-2 bg-light border rounded"),

            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.Strong("Nucleotides: ", className="me-2"),
                        html.Span("A", style={
                            'backgroundColor': NUCLEOTIDE_COLORS['A'],
                            'color': 'white',
                            'padding': '3px 10px',
                            'marginRight': '5px',
                            'fontFamily': 'Courier New, monospace',
                            'fontWeight': 'bold',
                            'borderRadius': '3px',
                            'border': '1px solid #ddd'
                        }),
                        html.Span("G", style={
                            'backgroundColor': NUCLEOTIDE_COLORS['G'],
                            'color': 'black',
                            'padding': '3px 10px',
                            'marginRight': '5px',
                            'fontFamily': 'Courier New, monospace',
                            'fontWeight': 'bold',
                            'borderRadius': '3px',
                            'border': '1px solid #ddd'
                        }),
                        html.Span("C", style={
                            'backgroundColor': NUCLEOTIDE_COLORS['C'],
                            'color': 'white',
                            'padding': '3px 10px',
                            'marginRight': '5px',
                            'fontFamily': 'Courier New, monospace',
                            'fontWeight': 'bold',
                            'borderRadius': '3px',
                            'border': '1px solid #ddd'
                        }),
                        html.Span("T", style={
                            'backgroundColor': NUCLEOTIDE_COLORS['T'],
                            'color': 'white',
                            'padding': '3px 10px',
                            'marginRight': '5px',
                            'fontFamily': 'Courier New, monospace',
                            'fontWeight': 'bold',
                            'borderRadius': '3px',
                            'border': '1px solid #ddd'
                        }),
                        html.Span("-", style={
                            'backgroundColor': NUCLEOTIDE_COLORS['-'],
                            'color': 'black',
                            'padding': '3px 10px',
                            'marginRight': '5px',
                            'fontFamily': 'Courier New, monospace',
                            'fontWeight': 'bold',
                            'borderRadius': '3px',
                            'border': '1px solid #999'
                        }),
                        html.Span(" ", style={'marginLeft': '30px', 'marginRight': '10px'}),
                        html.Span("●", style={
                            'color': '#FF4500',
                            'fontSize': '18px',
                            'marginRight': '5px',
                            'fontWeight': 'bold'
                        }),
                        html.Span("SNP", className="me-3"),
                        html.Span("◆", style={
                            'color': '#2196F3',
                            'fontSize': '20px',
                            'marginRight': '5px',
                            'fontWeight': 'bold'
                        }),
                        html.Span("Indel", className="me-3"),
                        html.Span("⁑", style={
                            'color': '#7B2CBF',
                            'fontSize': '20px',
                            'marginRight': '5px',
                            'fontWeight': 'bold'
                        }),
                        html.Span("Target SNP")
                    ], width=12)
                ])
            ], className="mt-2 mb-3 p-3 bg-light border rounded")
        ])

    except Exception as e:
        return html.Div(f"Error: {str(e)}", className="text-danger")


def auto_detect_variants(haplotypes, marker):
    """Auto-detect variants from sequences"""
    sequences = [h['haplotype_sequence'] for h in haplotypes]
    marker_position = marker['position_start']

    if len(sequences) < 2:
        return []

    max_len = max(len(seq) for seq in sequences)
    padded_seqs = [seq + '-' * (max_len - len(seq)) for seq in sequences]

    variants = []

    for pos_idx in range(max_len):
        bases_at_pos = [seq[pos_idx].upper() for seq in padded_seqs]
        unique_bases = set(bases_at_pos)

        if len(unique_bases) <= 1:
            continue

        base_counts = Counter(bases_at_pos)
        total_seqs = len(bases_at_pos)
        ref_allele = base_counts.most_common(1)[0][0]

        for alt_allele, count in base_counts.items():
            if alt_allele == ref_allele:
                continue

            frequency = count / total_seqs

            if ref_allele == '-' or alt_allele == '-':
                variant_type = 'Indel'
            else:
                variant_type = 'SNP'

            genomic_position = marker_position + pos_idx

            variants.append({
                'position': genomic_position,
                'variant_type': variant_type,
                'reference_allele': ref_allele if ref_allele != '-' else '',
                'alternate_allele': alt_allele if alt_allele != '-' else '',
                'frequency': frequency
            })

    return variants


def get_allele_sort_key(haplotype_name):
    """
    Create sort key for ordering alleles: Ref, Alt, RefMatch, AltMatch
    Format: marker_id|AlleleType_####
    """
    if '|' not in haplotype_name:
        return (5, 0)  # Unknown format, sort last

    allele_part = haplotype_name.split('|')[1]

    # Determine allele type and extract number
    if allele_part.startswith('Ref_'):
        return (0, int(allele_part.split('_')[1]))  # Ref first
    elif allele_part.startswith('Alt_'):
        return (1, int(allele_part.split('_')[1]))  # Alt second
    elif allele_part.startswith('RefMatch_'):
        return (2, int(allele_part.split('_')[1]))  # RefMatch third
    elif allele_part.startswith('AltMatch_'):
        return (3, int(allele_part.split('_')[1]))  # AltMatch fourth
    else:
        return (4, 0)  # Unknown type


def create_msa_figure(haplotypes, variants, marker, is_aligned=False, is_bottom_strand=False):
    """Create enhanced multiple sequence alignment visualization"""
    if not haplotypes:
        return go.Figure()

    haplotypes = sorted(haplotypes, key=lambda h: get_allele_sort_key(h['haplotype_name']), reverse=True)

    sequences = [h['haplotype_sequence'] for h in haplotypes]
    haplotype_names = [h['haplotype_name'] for h in haplotypes]

    seq_length = max(len(seq) for seq in sequences)

    target_snp_position = None
    ref_sequence = None
    alt_sequence = None
    for i, hap in enumerate(haplotypes):
        if 'Ref_' in hap['haplotype_name'] and not 'RefMatch' in hap['haplotype_name']:
            ref_sequence = sequences[i]
        elif 'Alt_' in hap['haplotype_name'] and not 'AltMatch' in hap['haplotype_name']:
            alt_sequence = sequences[i]

    if ref_sequence and alt_sequence:
        differences = []
        for pos in range(min(len(ref_sequence), len(alt_sequence))):
            if ref_sequence[pos].upper() != alt_sequence[pos].upper():
                differences.append(pos)

        if len(differences) == 1:
            target_snp_position = differences[0]
    consensus_sequence = []
    for i in range(seq_length):
        bases_at_pos = []
        for seq in sequences:
            if i < len(seq):
                bases_at_pos.append(seq[i].upper())
            else:
                bases_at_pos.append('-')

        base_counts = Counter(bases_at_pos)
        consensus_base = base_counts.most_common(1)[0][0] if base_counts else 'N'
        consensus_sequence.append(consensus_base)

    LIGHT_NUCLEOTIDE_COLORS = {
        'A': '#A3D9AC',
        'G': '#F9E1A8',
        'C': '#B5DDE8',
        'T': '#F2A7AE',
        '-': '#F5F5F5',
        'N': '#C8CACA'
    }

    variant_positions = {}
    for variant in variants:
        pos = variant['position']
        if pos not in variant_positions:
            variant_positions[pos] = []
        variant_positions[pos].append(variant)

    color_matrix = []
    text_matrix = []
    # For unaligned sequences, use white or very light gray to indicate raw data
    UNALIGNED_COLOR = '#FFFFFF'  # White for nucleotide cells in unaligned sequences
    
    for seq in sequences:
        color_row = []
        text_row = []
        for i in range(seq_length):
            if i < len(seq):
                base = seq[i].upper()
                text_row.append(base)

                if is_aligned:
                    # Use colored nucleotides for aligned sequences
                    consensus_base = consensus_sequence[i]
                    if base == consensus_base:
                        color_row.append(NUCLEOTIDE_COLORS.get(base, NUCLEOTIDE_COLORS['N']))
                    else:
                        color_row.append(LIGHT_NUCLEOTIDE_COLORS.get(base, LIGHT_NUCLEOTIDE_COLORS['N']))
                else:
                    # Use uniform color for unaligned sequences (raw data)
                    color_row.append(UNALIGNED_COLOR)
            else:
                if is_aligned:
                    color_row.append(LIGHT_NUCLEOTIDE_COLORS['-'])
                else:
                    color_row.append(UNALIGNED_COLOR)
                text_row.append('-')
        color_matrix.append(color_row)
        text_matrix.append(text_row)

    unique_colors = set()
    for row in color_matrix:
        unique_colors.update(row)
    unique_colors = sorted(list(unique_colors))
    color_to_num = {color: idx for idx, color in enumerate(unique_colors)}

    numeric_matrix = []
    for row in color_matrix:
        numeric_row = [color_to_num[color] for color in row]
        numeric_matrix.append(numeric_row)
    n_colors = len(unique_colors)
    colorscale = []
    
    # For unaligned sequences with uniform color, create a simple single-color colorscale
    if not is_aligned and n_colors == 1:
        colorscale = [[0, UNALIGNED_COLOR], [1, UNALIGNED_COLOR]]
    else:
        for i, color in enumerate(unique_colors):
            start = i / max(1, n_colors - 1) if n_colors > 1 else 0
            end = (i + 0.99999) / max(1, n_colors - 1) if n_colors > 1 else 1
            colorscale.append([start, color])
            if i < n_colors - 1:
                colorscale.append([end, color])

    if is_aligned:
        x_values = []
        if ref_sequence:
            genomic_offset = 0
            last_valid_genomic_pos = marker['position_start']
            gap_count = 0
            for align_pos in range(seq_length):
                if align_pos < len(ref_sequence):
                    ref_base = ref_sequence[align_pos].upper()
                    if ref_base != '-' and ref_base != 'N':
                        genomic_pos = marker['position_start'] + genomic_offset
                        x_values.append(genomic_pos)
                        last_valid_genomic_pos = genomic_pos
                        genomic_offset += 1
                        gap_count = 0
                    else:
                        gap_offset = 0.1 * (gap_count + 1)
                        x_values.append(last_valid_genomic_pos + gap_offset)
                        gap_count += 1
                else:
                    gap_offset = 0.1 * (gap_count + 1)
                    x_values.append(last_valid_genomic_pos + gap_offset)
                    gap_count += 1
        else:
            for align_pos in range(seq_length):
                x_values.append(marker['position_start'] + align_pos)
        
        x_title = 'Genomic Position'
        hover_template = '<b>Genomic Position:</b> %{x:,}<br><b>Allele:</b> %{y}<br><b>Base:</b> %{text}<extra></extra>'
    else:
        x_values = list(range(marker['position_start'], marker['position_start'] + seq_length))
        x_title = 'Genomic Position'
        hover_template = '<b>Genomic Position:</b> %{x:,}<br><b>Allele:</b> %{y}<br><b>Base:</b> %{text}<extra></extra>'

    target_snp_x_pos = None
    target_snp_absolute_x_pos = None
    if target_snp_position is not None:
        if is_aligned:
            if target_snp_position < len(x_values):
                x_pos = x_values[target_snp_position]
            else:
                if ref_sequence:
                    genomic_offset = 0
                    for align_pos in range(min(target_snp_position + 1, len(ref_sequence))):
                        if align_pos < len(ref_sequence):
                            ref_base = ref_sequence[align_pos].upper()
                            if ref_base != '-' and ref_base != 'N':
                                if align_pos == target_snp_position:
                                    x_pos = marker['position_start'] + genomic_offset
                                    break
                                genomic_offset += 1
                    else:
                        x_pos = marker['position_start'] + target_snp_position
                else:
                    x_pos = marker['position_start'] + target_snp_position
        else:
            x_pos = marker['position_start'] + target_snp_position

        target_snp_absolute_x_pos = x_pos
        target_snp_x_pos = x_pos
        x_values = relative_positions(x_values, target_snp_x_pos, is_bottom_strand)
        x_title = 'Relative Position to Target SNP'
        hover_template = '<b>Relative Position to Target SNP:</b> %{x:g}<br><b>Allele:</b> %{y}<br><b>Base:</b> %{text}<extra></extra>'
        target_snp_x_pos = 0

    # For unaligned sequences, ensure zmin and zmax are set correctly for single color
    if not is_aligned and n_colors == 1:
        zmin_val = 0
        zmax_val = 0
    else:
        zmin_val = 0
        zmax_val = n_colors - 1 if n_colors > 1 else 1
    
    # Keep unaligned sequence rows continuous so bases remain easy to read.
    x_cell_gap = 0 if not is_aligned else 0.5
    y_cell_gap = 2.0 if not is_aligned else 0.5
    
    fig = go.Figure(data=go.Heatmap(
        z=numeric_matrix,
        x=x_values,
        y=[f"{name.split('|')[-1]}" for name in haplotype_names],
        colorscale=colorscale,
        zmin=zmin_val,
        zmax=zmax_val,
        showscale=False,
        text=text_matrix,
        texttemplate='%{text}',
        textfont={"size": 12, "family": "Courier New, monospace", "color": "black"},
        hovertemplate=hover_template,
        xgap=x_cell_gap,
        ygap=y_cell_gap
    ))
    snp_positions = set()
    for variant in variants:
        variant_type = variant.get('variant_type', '').upper()
        if 'SNP' in variant_type and 'INDEL' not in variant_type:
            if is_aligned:
                snp_pos = variant.get('genomic_position')
                if snp_pos is None:
                    align_pos = variant.get('position', 0)
                    if ref_sequence and align_pos < len(ref_sequence):
                        genomic_offset = 0
                        for i in range(min(align_pos + 1, len(ref_sequence))):
                            if ref_sequence[i].upper() not in ['-', 'N']:
                                if i == align_pos:
                                    snp_pos = marker['position_start'] + genomic_offset
                                    break
                                genomic_offset += 1
                        if snp_pos is None:
                            genomic_offset = sum(1 for j in range(align_pos) 
                                               if j < len(ref_sequence) and ref_sequence[j].upper() not in ['-', 'N'])
                            snp_pos = marker['position_start'] + genomic_offset
            else:
                snp_pos = variant.get('position')
                if snp_pos and snp_pos < marker['position_start']:
                    snp_pos = marker['position_start'] + snp_pos
            
            if snp_pos is not None and target_snp_absolute_x_pos is not None:
                snp_pos = relative_position(snp_pos, target_snp_absolute_x_pos, is_bottom_strand)
            
            if snp_pos is not None:
                snp_positions.add(int(snp_pos))
    indel_positions = set()
    for variant in variants:
        variant_type = variant.get('variant_type', '').upper()
        if 'INDEL' in variant_type or variant_type == 'INDEL':
            if is_aligned:
                indel_pos = variant.get('genomic_position')
                if indel_pos is None:
                    align_pos = variant.get('position', 0)
                    align_pos_0based = variant.get('position_0based', align_pos - 1)
                    if ref_sequence and align_pos_0based < len(ref_sequence):
                        genomic_offset = 0
                        for i in range(min(align_pos_0based + 1, len(ref_sequence))):
                            if ref_sequence[i].upper() not in ['-', 'N']:
                                if i == align_pos_0based:
                                    indel_pos = marker['position_start'] + genomic_offset
                                    break
                                genomic_offset += 1
                        if indel_pos is None:
                            genomic_offset = sum(1 for j in range(align_pos_0based) 
                                               if j < len(ref_sequence) and ref_sequence[j].upper() not in ['-', 'N'])
                            indel_pos = marker['position_start'] + genomic_offset
            else:
                indel_pos = variant.get('position')
                if indel_pos and indel_pos < marker['position_start']:
                    indel_pos = marker['position_start'] + indel_pos
            
            if indel_pos is not None and target_snp_absolute_x_pos is not None:
                indel_pos = relative_position(indel_pos, target_snp_absolute_x_pos, is_bottom_strand)
            
            if indel_pos is not None:
                indel_positions.add(int(indel_pos))

    xaxis_autorange = 'reversed' if target_snp_absolute_x_pos is not None and is_bottom_strand else True
    integer_positions = []
    if x_values:
        integer_positions = sorted(set(int(pos) for pos in x_values if pos == int(pos)))
        if integer_positions:
            min_x = min(integer_positions)
            max_x = max(integer_positions)
            tick_texts = [f'{pos:,}' for pos in integer_positions]
            
            xaxis_config = dict(
                tickmode='array',
                tickvals=integer_positions,
                ticktext=tick_texts,
                tickangle=-90,
                showgrid=False,
                autorange=xaxis_autorange,
                tickfont=MSA_AXIS_TICK_FONT
            )
        else:
            min_x = min(x_values)
            max_x = max(x_values)
            xaxis_config = dict(
                tickmode='linear',
                tick0=int(min_x),
                dtick=1,
                tickangle=-90,
                tickformat=',d',
                showgrid=False,
                autorange=xaxis_autorange,
                tickfont=MSA_AXIS_TICK_FONT
            )
    else:
        min_x = marker['position_start']
        max_x = marker['position_start'] + seq_length - 1
        integer_positions = list(range(min_x, max_x + 1))
        xaxis_config = dict(
            tickmode='linear',
            tick0=marker['position_start'],
            dtick=1,
            tickangle=-90,
            tickformat=',d',
            showgrid=False,
            autorange=xaxis_autorange,
            tickfont=MSA_AXIS_TICK_FONT
        )

    top_marker_y = len(haplotypes) - 0.5 + 0.2
    if target_snp_position is not None:
        if len(haplotypes) <= 2:
            top_extension = 0.5
        elif len(haplotypes) <= 5:
            top_extension = 0.4
        else:
            top_extension = 0.3
        yaxis_range = [-0.5, len(haplotypes) - 0.5 + top_extension]
    else:
        if len(haplotypes) <= 2:
            top_extension = 0.4
        elif len(haplotypes) <= 5:
            top_extension = 0.3
        else:
            top_extension = 0.25
        yaxis_range = [-0.5, len(haplotypes) - 0.5 + top_extension]

    annotations = []
    # Only add variant markers for aligned sequences
    if is_aligned:
        if snp_positions and x_values and integer_positions:
            for snp_pos in snp_positions:
                if target_snp_x_pos is not None and int(snp_pos) == int(target_snp_x_pos):
                    continue
                if snp_pos >= min_x and snp_pos <= max_x and snp_pos in integer_positions:
                    annotations.append(dict(
                        x=snp_pos,
                        y=top_marker_y,
                        text='●',
                        showarrow=False,
                        xref='x',
                        yref='y',
                        xanchor='center',
                        yanchor='bottom',
                        font=dict(size=14, color='#FF4500', family='Arial, sans-serif'),
                        opacity=1.0
                    ))
        
        if indel_positions and x_values and integer_positions:
            for indel_pos in indel_positions:
                if indel_pos >= min_x and indel_pos <= max_x and indel_pos in integer_positions:
                    annotations.append(dict(
                        x=indel_pos,
                        y=top_marker_y,
                        text='◆',
                        showarrow=False,
                        xref='x',
                        yref='y',
                        xanchor='center',
                        yanchor='bottom',
                        font=dict(size=14, color='#2196F3', family='Arial, sans-serif'),
                        opacity=1.0
                    ))
        
        if target_snp_x_pos is not None and x_values and integer_positions:
            if target_snp_x_pos >= min_x and target_snp_x_pos <= max_x and int(target_snp_x_pos) in integer_positions:
                annotations.append(dict(
                    x=target_snp_x_pos,
                    y=top_marker_y,
                    text='⁑',
                    showarrow=False,
                    xref='x',
                    yref='y',
                    xanchor='center',
                    yanchor='bottom',
                    font=dict(size=18, color='#7B2CBF', family='Arial, sans-serif'),
                    opacity=1.0
                ))

    all_annotations = annotations

    fig.update_layout(
        title=dict(
            text=msa_chart_title(marker["marker_id"], is_bottom_strand),
            x=0.5,
            xanchor='center'
        ),
        height=max(400, len(haplotypes) * 30 + 120),
        template='plotly_white',
        xaxis=xaxis_config,
        yaxis=dict(
            showgrid=False,
            autorange=True,  # Enable autoscaling (removed fixed range)
            tickmode='array',
            tickvals=list(range(len(haplotypes))),
            ticktext=[f"{name.split('|')[-1]}" for name in haplotype_names],
            tickfont=MSA_AXIS_TICK_FONT,
            title=dict(text='Allele Variant', font=MSA_AXIS_TITLE_FONT)
        ),
        plot_bgcolor='#dee2e6' if not is_aligned else '#f8f9fa',  # Darker gray for unaligned to show grid lines better
        paper_bgcolor='#f8f9fa',  # Bootstrap bg-light color for the entire figure area (matches legend box)
        margin=dict(
            t=110,
            b=100, 
            l=150, 
            r=50
        ),
        annotations=all_annotations
    )
    fig.update_xaxes(title=dict(text=x_title, font=MSA_AXIS_TITLE_FONT))

    return fig


def create_variant_table(variants):
    """Create variant summary table"""
    if not variants:
        return html.Small("No variants detected", className="text-muted")

    rows = []
    for v in variants[:10]:
        badge_color = "warning" if v['variant_type'] == 'SNP' else "danger"
        row = html.Tr([
            html.Td(v['position']),
            html.Td(dbc.Badge(v['variant_type'], color=badge_color)),
            html.Td(v['reference_allele'] or '-'),
            html.Td(v['alternate_allele'] or '-'),
            html.Td(f"{v['frequency']:.3f}")
        ])
        rows.append(row)

    table = dbc.Table([
        html.Thead(html.Tr([
            html.Th("Position"),
            html.Th("Type"),
            html.Th("Ref"),
            html.Th("Alt"),
            html.Th("Freq")
        ])),
        html.Tbody(rows)
    ], size="sm", striped=True)

    return table


@app.callback(
    Output('navigate-to-haplotype-store', 'data'),
    Input({'type': 'haplotype-link-btn', 'index': dash.ALL}, 'n_clicks'),
    prevent_initial_call=True
)
def navigate_to_haplotype_explorer(n_clicks):
    """Store haplotype name and trigger navigation to Haplotype Explorer tab"""
    triggered = ctx.triggered_id

    if not triggered or not isinstance(triggered, dict):
        return no_update

    if triggered.get('type') != 'haplotype-link-btn':
        return no_update

    if n_clicks:
        has_real_click = any(clicks and clicks > 0 for clicks in n_clicks)
        if not has_real_click:
            return no_update

    haplotype_name = triggered.get('index')
    if not haplotype_name:
        return no_update

    return {'haplotype_name': haplotype_name}


@app.callback(
    Output('marker-alignment-store', 'data'),
    Input('marker-detail-store', 'data'),
    prevent_initial_call=True
)
def align_marker_sequences(marker_id):
    """Automatically align marker sequences using CLUSTAL Omega when marker is selected"""
    import time as _time
    if not marker_id:
        return {'status': 'original', 'marker_id': None, 'sequences': None, 'variants': None}

    _t0 = _time.time()
    print(f"[ALIGN] Starting alignment for {marker_id}")

    try:
        db = DatabaseManager()
        with db.shared_connection():
            haplotypes = get_microhaplotypes_for_marker(db, marker_id)
            marker = get_marker_details(db, marker_id)

        print(f"[ALIGN] {marker_id}: {len(haplotypes)} haplotypes, "
              f"seq lengths={[len(h['haplotype_sequence']) for h in haplotypes[:5]]}")

        if len(haplotypes) < 2:
            print(f"[ALIGN] {marker_id}: skipped — fewer than 2 haplotypes")
            return {'status': 'original', 'marker_id': marker_id, 'sequences': None, 'variants': None}

        seq_records = []
        for hap in haplotypes:
            seq = Seq(hap['haplotype_sequence'])
            record = SeqRecord(seq, id=hap['haplotype_name'], description="")
            seq_records.append(record)

        aligner = MSAAligner(algorithm='clustal')
        alignment = aligner.align_sequences(seq_records)

        annotator = VariantAnnotator(min_frequency=0.1)
        aligned_variants_raw = annotator.annotate_alignment(alignment)

        target_snp_position = None
        ref_record = None
        alt_record = None
        for record in alignment:
            if 'Ref_' in record.id and 'RefMatch' not in record.id:
                ref_record = record
            elif 'Alt_' in record.id and 'AltMatch' not in record.id:
                alt_record = record

        if ref_record and alt_record:
            differences = []
            for pos in range(min(len(ref_record.seq), len(alt_record.seq))):
                if str(ref_record.seq[pos]).upper() != str(alt_record.seq[pos]).upper():
                    differences.append(pos)

            if len(differences) == 1:
                target_snp_position = differences[0]

        aligned_variants = []
        for var in aligned_variants_raw:
            alignment_position_1based = var.get('position', 0)
            alignment_position = var.get('position_0based', alignment_position_1based - 1)
            
            genomic_position = None
            if ref_record:
                ref_seq = str(ref_record.seq)
                if alignment_position < len(ref_seq):
                    genomic_offset = 0
                    for i in range(alignment_position + 1):
                        if i < len(ref_seq):
                            ref_base = ref_seq[i].upper()
                            if ref_base not in ['-', 'N']:
                                if i == alignment_position:
                                    genomic_position = marker['position_start'] + genomic_offset
                                    break
                                genomic_offset += 1
                    
                    if genomic_position is None:
                        genomic_offset = sum(1 for j in range(alignment_position) 
                                           if j < len(ref_seq) and ref_seq[j].upper() not in ['-', 'N'])
                        genomic_position = marker['position_start'] + genomic_offset
                else:
                    genomic_offset = sum(1 for j in range(len(ref_seq)) 
                                       if ref_seq[j].upper() not in ['-', 'N'])
                    genomic_position = marker['position_start'] + genomic_offset
            else:
                genomic_position = marker['position_start'] + alignment_position
            if 'INDEL' in var.get('type', '').upper():
                variant_type = 'Indel'
            elif alignment_position == target_snp_position:
                variant_type = 'Target_SNP'
            else:
                variant_type = 'SNP'

            aligned_variants.append({
                'position': alignment_position,
                'genomic_position': genomic_position,
                'variant_type': variant_type,
                'reference': var.get('reference', 'N'),
                'alternates': var.get('alternates', []),
                'frequencies': var.get('frequencies', {})
            })

        aligned_data = []
        for record in alignment:
            aligned_data.append({
                'haplotype_name': record.id,
                'haplotype_sequence': str(record.seq)
            })

        print(f"[ALIGN] {marker_id}: SUCCESS in {_time.time() - _t0:.1f}s — "
              f"{len(aligned_data)} seqs, {len(aligned_variants)} variants")
        return {
            'status': 'aligned',
            'marker_id': marker_id,
            'sequences': aligned_data,
            'variants': aligned_variants
        }

    except Exception as e:
        import traceback
        print(f"[ALIGN] {marker_id}: FAILED in {_time.time() - _t0:.1f}s — {e}")
        traceback.print_exc()
        return {
            'status': 'original',
            'marker_id': marker_id,
            'sequences': None,
            'variants': None,
            'error': str(e)
        }


@app.callback(
    Output('marker-alignment-store', 'data', allow_duplicate=True),
    Input('show-original-btn', 'n_clicks'),
    State('marker-alignment-store', 'data'),
    prevent_initial_call=True
)
def toggle_alignment_view(n_clicks, alignment_data):
    """Toggle between aligned and original sequences"""
    # Dynamic component insertion can invoke this callback with n_clicks unset.
    # Only toggle when the user actually clicked the button.
    if not n_clicks:
        return no_update

    if not alignment_data:
        return {'status': 'original', 'marker_id': None, 'sequences': None, 'variants': None}

    # Ignore clicks until there is data to toggle between.
    if not alignment_data.get('marker_id') or alignment_data.get('sequences') is None:
        return no_update
    
    current_status = alignment_data.get('status', 'original')
    
    if current_status == 'aligned':
        return {**alignment_data, 'status': 'original'}
    else:
        return {**alignment_data, 'status': 'aligned'}


@app.callback(
    [Output('msa-graph', 'figure'),
     Output('alignment-status-message', 'children'),
     Output('show-original-btn', 'children')],
    [Input('marker-alignment-store', 'data'),
     Input('marker-detail-store', 'data')],
    prevent_initial_call=True
)
def update_msa_visualization(alignment_data, marker_id):
    """Update MSA visualization based on alignment status.

    Must react to BOTH marker-alignment-store (alignment finished) AND
    marker-detail-store (marker selected).  The second input guarantees
    the callback fires in the same Dash response cycle that creates the
    dynamic msa-graph component, so the output reliably reaches the
    newly-mounted graph.
    """
    if not marker_id:
        empty_fig = go.Figure()
        empty_fig.update_layout(template='plotly_white', xaxis={'visible': False}, yaxis={'visible': False})
        return empty_fig, html.Div(), [html.I(className="fas fa-undo me-2"), "Show Original (Unaligned)"]

    try:
        db = DatabaseManager()
        with db.shared_connection():
            marker = get_marker_details(db, marker_id)
            bottom_loci_count = get_botloci_count(db)
            marker_is_bottom_strand = is_bottom_locus(db, marker_id)

        alignment_matches_marker = (
            alignment_data and
            alignment_data.get('marker_id') == marker_id
        )

        if not alignment_matches_marker:
            loading_fig = go.Figure()
            loading_fig.update_layout(
                template='plotly_white',
                xaxis={'visible': False},
                yaxis={'visible': False},
                annotations=[{
                    'text': 'Aligning sequences...',
                    'xref': 'paper',
                    'yref': 'paper',
                    'x': 0.5,
                    'y': 0.5,
                    'showarrow': False,
                    'font': {'size': 20, 'color': '#999'}
                }]
            )
            loading_status = dbc.Alert([
                html.I(className="fas fa-spinner fa-spin me-2"),
                "Running CLUSTAL Omega alignment..."
            ], color="secondary", className="mt-2")
            return loading_fig, loading_status, [html.I(className="fas fa-dna me-2"), "Show Aligned"]

        use_aligned = (
            alignment_matches_marker and
            alignment_data.get('status') == 'aligned' and
            alignment_data.get('sequences') and
            alignment_data.get('variants') is not None
        )

        if use_aligned:
            haplotypes = alignment_data['sequences']
            variants = alignment_data['variants']
            is_aligned = True
            num_variants = len(variants)
            status_message = dbc.Alert([
                html.I(className="fas fa-check-circle me-2"),
                f"Sequences aligned using CLUSTAL Omega ({num_variants} variants detected)"
            ], color="success", className="mt-2", dismissable=True)
            button_text = [html.I(className="fas fa-undo me-2"), "Show Original (Unaligned)"]
        else:
            with db.shared_connection():
                haplotypes = get_microhaplotypes_for_marker(db, marker_id)
                variants = get_variants_for_marker(db, marker_id)
            if not variants and haplotypes:
                variants = auto_detect_variants(haplotypes, marker)
            is_aligned = False

            if alignment_matches_marker and alignment_data.get('error'):
                status_message = dbc.Alert([
                    html.I(className="fas fa-exclamation-triangle me-2"),
                    f"Alignment failed: {alignment_data['error']}"
                ], color="warning", className="mt-2", dismissable=True)
            elif alignment_matches_marker and alignment_data.get('sequences'):
                status_message = dbc.Alert([
                    html.I(className="fas fa-info-circle me-2"),
                    "Showing original (unaligned) sequences"
                ], color="info", className="mt-2", dismissable=True)
            elif alignment_matches_marker and len(haplotypes) < 2:
                status_message = dbc.Alert([
                    html.I(className="fas fa-info-circle me-2"),
                    f"Showing original sequences ({len(haplotypes)} allele)"
                ], color="info", className="mt-2", dismissable=True)
            else:
                status_message = html.Div()
            button_text = [html.I(className="fas fa-dna me-2"), "Show Aligned"]

        botloci_warning = None
        if bottom_loci_count == 0:
            botloci_warning = dbc.Alert([
                html.I(className="fas fa-exclamation-triangle me-2"),
                "No bottom-loci file has been uploaded. MSA strand orientation may be incorrect for bottom-strand loci."
            ], color="warning", className="mt-2 mb-0", dismissable=True)

        if botloci_warning:
            status_message = html.Div([botloci_warning, status_message])

        msa_fig = create_msa_figure(
            haplotypes,
            variants,
            marker,
            is_aligned,
            marker_is_bottom_strand
        )

        return msa_fig, status_message, button_text

    except Exception as e:
        error_fig = go.Figure()
        error_fig.add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
        return error_fig, html.Div(), [html.I(className="fas fa-dna me-2"), "Show Aligned"]


@app.callback(
    [Output('marker-left-panel-minimized', 'data'),
     Output('marker-left-col', 'width'),
     Output('marker-right-col', 'width'),
     Output('marker-filters-body', 'style'),
     Output('marker-results-card', 'style'),
     Output('marker-minimize-icon', 'className'),
     Output('marker-search-title', 'style'),
     Output('marker-search-icon', 'style')],
    Input('marker-minimize-btn', 'n_clicks'),
    State('marker-left-panel-minimized', 'data'),
    prevent_initial_call=True
)
def toggle_marker_left_panel(n_clicks, is_minimized):
    """Toggle left panel between minimized and expanded states"""
    new_state = not is_minimized
    
    if new_state:
        return (
            True,
            1,
            11,
            {'display': 'none'},
            {'display': 'none'},
            "fas fa-chevron-right",
            {'display': 'none'},
            {'display': 'none'}
        )
    else:
        return (
            False,
            3,
            9,
            {},
            {},  # Show results (no internal scrolling)
            "fas fa-chevron-left",
            {},
            {'marginRight': '0.5rem'}
        )
