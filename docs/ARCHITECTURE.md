# How I built this

I started the app with `./start.sh`, which served http://127.0.0.1:8000. I copied `.env.example` to `.env` and put the key in `OPENAI_API_KEY`. `start.sh` loaded that file, so the chat process could see the key.

On each start I reread the drawings and the bill of materials and wrote a fresh `data/knowledge.sqlite`. I kept accept and reject decisions in `data/corrections.sqlite`. A restart rebuilt the knowledge file and left the review log where it was.

## What I used, and why

I wanted one local process I could start from a script, with an answer I could trace back to a row.

I used Python to read the spreadsheet and the PDFs, store them, and answer the question. One language kept the path from a file on disk to a sentence on the screen short enough that I could walk it.

I used pypdf to pull the text out of each drawing. On a faded scan that text came back empty, and I treated the empty result as a fact. The chat then said the sheet could not be read.

I stored the data in two ordinary SQLite files, so I never stood up a separate database server.

I used FastAPI and Uvicorn as the server `start.sh` started.

I wrote the page in plain HTML, CSS, and JavaScript, so there was no front-end build. When a drawing opened, I rendered that page to a PNG with PDFium and cached it under `data/pages/`. The original PDF stayed one click away. I wrote the orbit view as a short WebGL program in `web/viewer3d.js`.

For the wording of an answer I called an OpenAI-compatible chat endpoint with the Python standard library. I sent the question and the records I had already retrieved. The model wrote the sentences. I kept drawing selection, correction filing, and citations on those records. `OPENAI_MODEL` defaulted to `gpt-4o-mini`, and `OPENAI_BASE_URL` defaulted to `https://api.openai.com/v1`, so the same call worked against another compatible endpoint. If the key was missing, the chat said so and waited for the key.

## How the pieces worked

**I only kept words I could find on the sheet.** I wrote the names, materials, and the sizes used for the 3D parts in `app/catalog.py`. PDF text came out jumbled, so I read each sheet once and recorded the phrases. When the database was built, every one of those phrases was checked against the file. If a phrase was missing, the build stopped. For the eight scans with no text, the name came from the filename, and the app said so.

**I stored knowledge and reviews apart.** I could throw the knowledge file away and rebuild it from the dataset. The review file was a log. Each proposal stayed there as pending, accepted, or rejected. An accepted proposal changed later answers, and the answer kept the original bill-of-materials cell next to the new value.

**I linked a drawing to a part only when I could say why.** Each link was one of three kinds:

- *Depicts* meant I was confident this sheet was that part.
- *Candidate* meant it might be, and the answer said the match was unsettled.
- *Rejected* meant the names looked alike and the parts were still different.

The powder motor plate on drawing D-010 was 2 mm stainless steel. The build-plate motor plate in the bill of materials was aluminium. I left those two rejected, and the answer said they were different parts. The door drawing was named Door_x2 and the scan had no text, so I left it linked to both the front door and the back door.

**I followed a connection in both directions.** A row often left "Interface with" blank, while some other row named it. Asking what touched the front door found the hinge and the latch, because those rows named the door.

**I copied materials as they were written.** If a cell said `Stainless steel,Steel`, the part counted as both. I left a blank cell out of "which parts are stainless", because a blank was an empty cell. I listed the drawing statement and the bill-of-materials statement separately. When the drawing said 6061 and the bill of materials only said Aluminium, I described that as a more specific note on the drawing. It became the value I used in answers only after someone accepted a correction.

**I built the 3D parts as simple shapes from the numbers on the drawing.**

- The window clamp frame, D-005, was 323 by 236 mm, with an opening of 297.2 by 210.2 mm. The thickness was the 8.2 mm callout. The note that it held a 210 by 297 mm window was why I oriented the opening that way.
- The dispenser shaft, D-007, had lengths 29, 269.5, and 37.6 mm. Those added up to the 336.1 mm overall length, so I treated them as the three sections. I put the 8 mm ends on the outside and 25 mm in the middle as a reasoned guess, and the screen said so.
- The powder motor plate, D-010, was 107 by 70 by 2 mm. The 2 mm came from the sentence that said the plate was 2 mm stainless steel.

I left holes, grooves, and threads out. Dragging the view rotated the camera. The colored axes belonged to the view, and I used them as a camera aid. There was no original CAD model in this set of files, so I labeled the shape as a reconstruction from the 2D sheet.

**I looked up a whole part name before I called the model.** The word "plate" by itself matched too many things, so I kept a lone "plate" from opening a part. In the phrase "build-plate motor plate", the words "build plate" described where the motor plate sat, and I left the Build Plate part closed. When a drawing and a bill-of-materials row depicted each other, I answered them together. Any other match stayed a separate record. If the question was about material, cost, connections, or size, that part of the packet came first. I fixed the packet, the citations, and the drawing I opened before the model saw them. The model wrote the sentences from that packet. If the records did not support the question, the packet said so, and I told the model to abstain.

I kept help, history, and a correction proposal off the model. Those replies had to stay word for word, because Review showed the check I froze when the proposal was filed. Accepting or rejecting left that check as it was.

**I described a kind of shop, and I kept supplier names to the ones in the bill of materials.** For a custom stainless sheet I said a laser-cutting shop fitted the thickness and the weld-nut notes. That was a suggestion about the process, a class of shop, with price and stock left out.

## What I left out

The 3D view covered three parts, and those shapes left out holes and grooves.

I quoted hole notes I could see in the text. I left the rest of the dimensions on a sheet as text.

The eight degraded drawings contributed a filename, a note about how the scan was made, and a picture. I left their title blocks unread as text.

I kept empty costs, a recorded cost of DKK 0.00, and old supplier links as they appeared in the snapshot.

Electrical parts and sensor-gantry parts could be asked about in chat. They appeared on the graph only when a drawing or a connection reached them.

`python -m app.evaluate` wrote `data/evaluation.json` with the model name, how long each answer took, and the window-frame answer before and after the correction. With no key, that file recorded the missing-key reply. `tests/test_answers.py` checked the retrieval with a stand-in that echoed the packet, so those checks stayed off the network. A second test posted a chat completion through the real client against a stand-in HTTP response, so I knew the request was a real API call.
