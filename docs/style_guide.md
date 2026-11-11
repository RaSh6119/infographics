# Infographic style guide

Describes the reference set `data/ground_truth/R00 Infographics_English_CO.pdf`: 16 pages, numbered
1E, 2E, 2aE and 3E-15E. The PDF is not tracked by git. Its topic is HIV treatment; our infographics
are about HIV prevention, so the style carries over and the medical content does not.

This is a visual reference, not a template. Models should learn how figures and objects are drawn
and coloured, and are free to choose their own layout. Nothing here is a required structure, and
the references' text should not be copied.

Colours, fonts and sizes were read from the PDF's vector data. The role of each one was judged by
eye from the rendered pages.

## Page

- Landscape, 1194 x 834 pt (about 1.43:1), which is 1080 x 754 px at our contract width.
- White background with no panels, shadows or background textures.
- One idea per page, with generous empty space.

## Colour

| Role | Colour | Hex |
|---|---|---|
| Titles, labels, outlines, dark objects | Navy | `#08344c` |
| Title underline, page code, soft accents | Sky blue | `#51b4d6` |
| Human figures | Mid gray | `#b3b3b3` |
| Warnings, "no" signs, hearts, emphasised words, negative arrows | Red | `#eb4f41` |
| Flow arrows, timeline bars, table headings | Blue | `#3576bc` |
| Pills | Slate blue | `#6283bb` |
| Positive arrows, time labels, "good" end of a scale | Green | `#66aa67` |

Topic-specific accents: purple `#7565a9` (virus), yellow `#fcd41b` (CD4 cells), tan `#eed296`
(second pill). Saturated colour is reserved for what the page is about; everything else stays gray
or navy.

## Type

- Titles: Poppins Bold, about 58 pt, navy, sentence case, left aligned at the top.
- Labels: Inter SemiBold, 18-25 pt, navy, centred under or beside their symbol.
- Section headings and key numbers: Inter Bold or ExtraBold, 34-50 pt.
- Few words: labels are usually 1-6 words, with no paragraphs anywhere.

## Recurring structure

- A title with a sky-blue rule under it. The rule runs in from the left edge and stops just past the
  end of the title.
- A small sky-blue page code at the bottom right.
- Symbols carry the meaning and text labels them, rather than the reverse.

## Symbols

- Flat vector pictograms: solid fills, no gradients on objects, no photos, no 3D.
- People are faceless gray figures with round heads, shown only by posture. A face or colour appears
  only when it conveys a state, such as illness.
- Thin navy outlines are used for containers such as circles and tables.
- Recurring motifs: capsule, medication bottle, thought and speech bubbles, heart, red "no" circle
  with a slash, block arrow, dotted zoom lines into a detail, red-yellow-green scale bar.

## Layouts by infographic type

| Type | Reference pages | Layout |
|---|---|---|
| Statistical | 14E, 15E | Gradient scale bar with numbered ticks between two contrasting figures |
| Timeline | 4E | Horizontal blue arrow with dots, a figure above and a large label below each point |
| Process | 3E, 5E, 9E | Groups joined by block arrows, a segmented wheel, or a winding road |
| Comparison | 8E, 10E, 13E | Two sides split by a line or an equals sign, with the same symbols repeated |
| List | 1E, 6E, 7E | Scattered outlined circles, each holding one symbol and a short label |

Pages 2E, 2aE, 11E and 12E are a schedule table, a figure group and an explanatory diagram, and don't
fit one of the five types cleanly.
