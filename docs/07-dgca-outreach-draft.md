# 07 — DGCA/MoSPI Outreach Draft (Q4)

Per `docs/05-open-questions.md` Q4: "the downside is a letter; the upside
changes the project's category." This is that letter, drafted so sending it
is a copy-paste-and-send action, not a from-scratch writing task. Not sent by
me — outbound correspondence to a government body is yours to send under your
own name.

Two versions below: a short one to DGCA's Tariff Monitoring Unit angle
(closer institutional fit, per docs/01's finding that DGCA TMU already does
monthly manual monitoring of ~78 routes) and a short one to MoSPI (closer to
the CPI 2024 "alternative data sources" commitment angle from docs/00). Send
whichever fits the contact you actually have, or both if you have two
separate contacts — they're not mutually exclusive.

---

## Version A — DGCA Tariff Monitoring Unit angle

**Subject:** Independent daily airfare index — offering to complement DGCA's
Tariff Monitoring Unit's route coverage

Dear [Sir/Madam / named contact if known],

I'm building an independent, publicly-documented daily Airfare Price Index
(APIx) for Indian domestic routes, using DGCA-mandated public tariff sheet
disclosures (Rule 135(2), Aircraft Rules 1937 / DGCA Air Transport Circular
02 of 2010) as its primary data source — the same disclosure mechanism I
understand the Tariff Monitoring Unit already uses for its own monthly
monitoring of fares across roughly 78 routes.

I'm writing to ask two things, in order of how much they'd help:

1. **Would DGCA be willing to share historical tariff-sheet records or TMU
   monitoring data** covering the past 12–24 months? This would let me
   validate the index against a real historical baseline rather than only
   forward data collected from today onward — scraped fares cannot be
   collected retroactively, so this is the only route to a genuine back-test.
2. **Is there a published or shareable estimate of the booking-lead-time
   distribution** for Indian domestic passengers (the share of bookings made
   1 day, 7 days, 15 days, 30+ days before departure)? This is the single
   largest open methodological gap in constructing a composite fare index
   from advance-purchase-window data, and I don't believe it's publicly
   available anywhere else.

I'm collecting data only from legally mandated public disclosures and
consented public pages, respecting robots.txt and rate limits throughout —
happy to share the full methodology and architecture documentation if useful.

Regards,
[Your name]
[Contact email]

---

## Version B — MoSPI CPI 2024 angle

**Subject:** Prototype airfare price index — aligned with CPI 2024's
committed use of alternative data sources

Dear [Sir/Madam / named contact if known],

The CPI 2024 base-year series (released 12 February 2026) states a
commitment to "inclusion of alternative data sources" and "use of modern
technology" in price collection. I'm building a prototype that implements
exactly that for one COICOP 2018 class — passenger transport by air — and
wanted to flag it in case it's useful to whoever owns that commitment inside
MoSPI.

The system (APIx) collects daily airfare data from DGCA-mandated public
tariff disclosures, computes a Jevons/Lowe-Young price index with a
published revision policy and full audit trail back to raw source data, and
exposes it via an SDMX-compatible API — the exchange standard national
statistical offices already use.

Two questions, in case anyone there can help:

1. **Could you confirm the exact COICOP 2018 class code and All-India weight
   for passenger transport by air** in the CPI 2024 weighting diagram?
   I've been unable to retrieve this from mospi.gov.in / cpi.mospi.gov.in
   directly and don't want to publish an incorrect classification.
2. Is there an existing point of contact for external parties proposing
   alternative-data-source pipelines for CPI sub-indices? I'd rather route
   this through the right channel than guess.

Happy to share full documentation — methodology, architecture, and current
status — on request.

Regards,
[Your name]
[Contact email]

---

## Notes

- Both versions ask for something concrete, not just "are you interested" —
  a specific ask is easier to act on and easier to ignore gracefully if the
  answer is no.
- Neither promises anything the project can't actually deliver, and neither
  overclaims impact on headline CPI — consistent with `docs/00-scope.md` §5.
- If you get a reply either way (yes, no, or silence), update
  `docs/05-open-questions.md` Q3/Q4's status — silence after a reasonable
  wait is itself the answer needed to stop planning around option (c)
  (historical archive) in Q3.
