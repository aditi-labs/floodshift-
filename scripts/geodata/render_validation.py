"""Render a P4 validation figure; not P1 print artwork or P2 projector UI."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

from backend.world.demo import staged_world, place


def render(bundle, output):
    world = staged_world(bundle)
    before = world.snapshot()
    place(world, 'bridge', 'crossing_east')
    after = world.snapshot()
    scenario = world.scenario()
    fig, axes = plt.subplots(1, 2, figsize=(14, 8), facecolor='#f5f7f9')
    fig.suptitle('FLOODSHIFT · HOT-derived scenario validation', fontsize=19, fontweight='bold', y=.98)
    for ax, snapshot, title in zip(axes, (before, after), ('Before: three modeled crossing closures', 'After: selected temporary bridge placed')):
        ax.set_facecolor('#fcfcf9')
        for layer, color, width in [('roads', '#c9cdd3', .6), ('waterways', '#76bce4', 2.8)]:
            features = json.loads((Path(bundle) / 'data' / (layer + '_board.json')).read_text())['features']
            for feature in features:
                geometry = feature['geometry']
                parts = [geometry['coordinates']] if geometry['type'] == 'LineString' else geometry['coordinates']
                if geometry['type'] not in ('LineString', 'MultiLineString'):
                    continue
                for part in parts:
                    ax.plot(*zip(*part), color=color, linewidth=width, zorder=1)
        for edge in snapshot['edges']:
            ax.plot(*zip(*edge['board_uv']), color='#d45151' if edge['blocked'] else '#657589',
                    linewidth=2.2, linestyle='--' if edge['blocked'] else '-', zorder=2)
        for route in snapshot['routes']:
            ax.plot(*zip(*route['board_uv']), color='#12845b', linewidth=2.5, zorder=3)
        labels = {'medical_site_west': 'Field care*', 'food_site_west': 'Food/water*',
                  'shelter_site_west': 'Refuge*', 'people_east': 'Model household*', 'start_pad': 'START',
                  'crossing_east': 'Selected crossing'}
        offsets = {'crossing_east': (8, 16), 'people_east': (18, -2), 'start_pad': (-19, -18)}
        left, top, right, bottom = scenario['board']['control_inset_uv']
        ax.add_patch(Rectangle((left, top), right-left, bottom-top,
                              facecolor='white', edgecolor='#8793a1', zorder=4))
        ax.text((left+right)/2, top+.035, 'CONTROL', ha='center', fontsize=8, color='#657589', zorder=5)
        for site in scenario['sites']:
            if site['id'] not in labels:
                continue
            uv = site['board_uv']
            color = '#a03ee3' if site['kind'] == 'bridge_crossing' else '#1b344f'
            ax.scatter(*uv, color=color, s=38, zorder=5)
            ax.annotate(labels[site['id']], uv, xytext=offsets.get(site['id'], (7, 5)),
                        textcoords='offset points', fontsize=9, color=color,
                        bbox={'facecolor': 'white', 'alpha': .85, 'edgecolor': 'none', 'pad': 1.5}, zorder=5)
        ax.set_xlim(0, 1); ax.set_ylim(1, 0); ax.set_aspect('equal')
        ax.set_title(title, fontsize=12, pad=12)
        ax.set_xlabel('Board u · one shared square frame')
        ax.set_ylabel('Board v · top-left origin')
        metrics = snapshot['metrics']
        ax.text(.5, -.13, f"Unmet model units: food {metrics['unmet_food_model']}  |  care {metrics['unmet_medical_model']}  |  refuge {metrics['unmet_refuge_model']}",
                transform=ax.transAxes, ha='center', fontsize=11, fontweight='bold')
    handles = [Line2D([], [], color=c, lw=3, label=l) for c,l in
               [('#76bce4','Mapped waterways'),('#c9cdd3','Map context'),('#657589','Curated model roads'),
                ('#d45151','Modeled closures'),('#12845b','Computed service routes')]]
    fig.legend(handles=handles, loc='lower center', ncol=5, bbox_to_anchor=(.5,.08), frameon=False, fontsize=9)
    fig.text(.5,.065,'*Service pads and households are hypothetical game presets. Mapped geometry does not establish safety or operability.', ha='center', fontsize=10)
    fig.text(.5,.035,'© OpenStreetMap contributors · HOT / HDX NPL_CORRIDOR · ODbL · educational model, not emergency routing', ha='center', fontsize=9, color='#465264')
    fig.subplots_adjust(top=.89, bottom=.23, left=.06, right=.97, wspace=.17)
    fig.savefig(output, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=Path('scenarios/nepal_rasuwa_hot_v1'))
    parser.add_argument('--output', type=Path, default=Path('scenarios/nepal_rasuwa_hot_v1/data/validation_map.png'))
    args = parser.parse_args()
    render(args.bundle, args.output)
