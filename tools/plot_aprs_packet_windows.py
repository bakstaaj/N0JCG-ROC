#!/usr/bin/env python3
import re, wave
from datetime import datetime
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from scipy import signal

root=Path(__import__('sys').argv[1]); out=Path(__import__('sys').argv[2]); out.mkdir(parents=True,exist_ok=True)
for phase in sorted(root.glob('phase-*')):
    meta=dict(x.split('=',1) for x in (phase/'metadata.txt').read_text().splitlines() if '=' in x)
    start=datetime.fromisoformat(meta['started_utc'].replace('Z','+00:00'))
    with wave.open(str(phase/'audio-ring.wav'),'rb') as w:
        rate=w.getframerate(); data=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(float)
    event=None
    for line in (phase/'service-journal.log').read_text(errors='replace').splitlines():
        if 'BADGR' not in line or '] ' not in line: continue
        try: t=datetime.fromisoformat(line.split()[0].replace('Z','+00:00'))
        except ValueError: continue
        event=(t-start).total_seconds(); break
    if event is None: continue
    lo=max(0,int((event-2)*rate)); hi=min(len(data),int((event+2)*rate)); x=np.arange(lo,hi)/rate-event; y=data[lo:hi]
    fig,ax=plt.subplots(2,1,figsize=(12,6),constrained_layout=True)
    ax[0].plot(x,y,lw=.4); ax[0].set(title=f'{phase.name}: first BADGR event',ylabel='PCM amplitude',xlabel='Seconds from decoder timestamp'); ax[0].grid(alpha=.25)
    f,tt,S=signal.spectrogram(y,fs=rate,nperseg=1024,noverlap=768,scaling='spectrum'); ax[1].pcolormesh(tt+x[0],f/1000,10*np.log10(S+1e-12),shading='auto'); ax[1].set_ylim(0,4); ax[1].set(xlabel='Seconds from decoder timestamp',ylabel='Frequency (kHz)'); ax[1].grid(alpha=.2)
    fig.savefig(out/(phase.name+'.png'),dpi=140); plt.close(fig)
