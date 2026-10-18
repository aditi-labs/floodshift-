"""Render an offline QA figure, not a replacement for P2's live interface."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon


def render(report_path, output):
    report=json.loads(Path(report_path).read_text())
    data=Path(__file__).resolve().parents[2]/'scenarios/nepal_rasuwa_reasoning_v1/data'
    hazard=json.loads((data/'hazard.json').read_text())
    snapshot=report['snapshot'];decision=snapshot['routing_decision']
    fig,(ax,notes)=plt.subplots(1,2,figsize=(14,8),gridspec_kw={'width_ratios':[1.25,1]},facecolor='white')
    geom=hazard['footprints'][snapshot['simulation_stage']-1]['geometry']
    polygons=[geom['coordinates']] if geom['type']=='Polygon' else geom['coordinates']
    for poly in polygons:
        ax.add_patch(Polygon(poly[0],facecolor='#9dcfe8',edgecolor='none',alpha=.65))
    for edge in snapshot['edges']:
        ax.plot(*zip(*edge['board_uv']),color='#c96767' if edge['blocked'] else '#727c85',lw=1.5,zorder=2)
    colors=['#7b3294','#00866e','#e07a1c','#2b60ac']
    for group,color in zip(decision['groups'],colors):
        node=next(n for n in snapshot['routing_nodes'] if n['id']==group['origin_node'])
        ax.scatter(*node['board_uv'],s=70,color=color,zorder=5)
        ax.annotate(group['group_id'].replace('group-',''),node['board_uv'],xytext=(5,9),textcoords='offset points',color=color,fontsize=10,zorder=6)
        for route in group['routes']:
            ax.plot(*zip(*route['board_uv']),color=color,lw=2.6,alpha=.8,zorder=3)
    for facility in snapshot['facilities']:
        node=next(n for n in snapshot['routing_nodes'] if n['id']==facility['node_id'])
        ax.scatter(*node['board_uv'],marker='s',s=48,color='#253c4b',zorder=4)
    ax.set_xlim(0,1);ax.set_ylim(1,0);ax.set_aspect('equal');ax.set_xlabel('Board u');ax.set_ylabel('Board v')
    ax.set_title('Mapped roads + modeled flood footprint',fontsize=13)
    notes.axis('off')
    notes.text(0,1,'Population routing after a piece moves',fontsize=17,weight='bold',va='top')
    y=.91
    for group,color in zip(decision['groups'],colors):
        notes.text(0,y,group['group_id'],fontsize=13,color=color,weight='bold');y-=.045
        notes.text(0,y,f"Assigned {group['assigned_fraction']:.0%} | unassigned {group['unassigned_fraction']:.0%}",fontsize=11);y-=.04
        for route in group['routes']:
            notes.text(.02,y,f"{route['fraction']:.0%} → {route['shelter_id']}",fontsize=10);y-=.035
        if not group['routes']:
            notes.text(.02,y,'No open route in this scenario.',fontsize=10);y-=.035
        y-=.025
    notes.text(0,.19,'How the choice is made',fontsize=12,weight='bold')
    notes.text(0,.15,'Route as much as possible; share scarce capacity fairly;\nreduce peak crowding, then modeled travel time.\nGroups have no assigned headcount.',fontsize=10,va='top',linespacing=1.6)
    fig.suptitle('FLOODSHIFT · Nepal reasoning validation',fontsize=21,weight='bold',y=.98)
    fig.text(.06,.055,'Blue: modeled hazard footprint. Red: conservatively closed roads. Colored lines: assigned group routes.',fontsize=10)
    fig.text(.06,.033,'82/90 wet pixels carry a source quality warning. Regional hazard model, not a verified local evacuation map.',fontsize=10,color='#9a3030')
    fig.text(.06,.013,'© OpenStreetMap contributors · HOT/HDX · Copernicus Emergency Management Service, Global Flood Hazard Maps v2.1.2',fontsize=9)
    fig.subplots_adjust(top=.89,bottom=.12,wspace=.18)
    fig.savefig(output,dpi=140);plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();render(args.report,args.output)
