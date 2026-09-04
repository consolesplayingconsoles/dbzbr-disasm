#!/usr/bin/env python3
import sys, json
from capstone import *
ROM=open(sys.argv[1],'rb').read()
tr=json.load(open(sys.argv[2]))
lab={int(k,16):v for k,v in tr['labels'].items()}
md=Cs(CS_ARCH_M68K, CS_MODE_BIG_ENDIAN|CS_MODE_M68K_000)
lo=int(sys.argv[3],16); hi=int(sys.argv[4],16)
for pc in tr['starts']:
    if not (lo<=pc<hi): continue
    ins=next(md.disasm(ROM[pc:pc+16],pc,count=1),None)
    if ins is None: continue
    tag=lab.get(pc,'')
    print('%06X %-4s %-9s %s'%(pc, tag, ins.mnemonic, ins.op_str))
