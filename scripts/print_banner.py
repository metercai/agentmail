#!/usr/bin/env python3
"""Print a centered ASCII banner. Called by integrate.sh."""
import shutil, sys, os

title = os.environ.get("TITLE", "Agentmail and  Hermes Integration Wizard")
tw = shutil.get_terminal_size().columns
bw = min(tw, 58) if tw >= 50 else 50
w = sum(2 if ord(c) > 0x2e80 else 1 for c in title)
left = (bw - w) // 2
right = bw - w - left

line = "═" * bw
spaces_l = " " * left
spaces_r = " " * right

print(f"\033[1m╔{line}╗\033[0m")
print(f"\033[1m║{spaces_l}{title}{spaces_r}║\033[0m")
print(f"\033[1m╚{line}╝\033[0m")
