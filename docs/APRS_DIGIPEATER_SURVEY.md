# Passive APRS digipeater survey

The ROC now exposes `/api/aprs/digipeaters` and displays a 72-hour survey in
the APRS workspace. The survey is receive-only: it inspects RF frames already
decoded by Dire Wolf and records only path elements marked with `*`, which
means a digipeater actually used that path slot.

Unused aliases such as `WIDE2-2` are not treated as evidence of a digipeater.
Internet-only `[ig]` frames are excluded. When a relayed frame includes a
position, the dashboard estimates the source station's distance from the ROC
and lists the source stations that produced the observation. This is not a
digipeater location unless the digipeater itself transmitted a position beacon.

An empty survey means no digipeater hop was observed by this receiver during
the window; it is not proof that no digipeater exists outside the ROC's RF
coverage or during a quiet period.
