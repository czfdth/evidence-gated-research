#!/usr/bin/env python3
"""Isolated child: executable crash stage is os._exit, never simulated exception."""
import argparse
from experiments.cross_service_audit_v37 import Coordinator
p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--url',required=True);p.add_argument('--upstream');p.add_argument('--stage');p.add_argument('--method',choices=['WRITE','READ'],required=True);a=p.parse_args()
c=Coordinator(a.root,a.url,signing=True)
if a.method=='WRITE':c.write('m0',.731,'2026-10-10T12:15:00','crash-target-write',crash=a.stage)
else:c.read('paris museum tickets','2026-10-10T12:15:00',a.upstream,'crash-target-read',crash=a.stage)
c.close()