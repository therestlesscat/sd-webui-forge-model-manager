# Changelog

Every version of the extension, newest first. A version is MAJOR.MINOR.PATCH.BUILD:
a minor version is a feature that stands on its own, a patch is any other change you
can see, up to the next minor version, and the build is the commit's place in the
repository's history. A change that only touches tests, documentation or the code's
structure keeps its version and moves the build on, and is not listed here.

## 0.40 - Generations

*29 September 2026*

A Generations tab, before the Model Manager, holds every image you have generated, newest first, whatever model made it: a tile per generation - a batch its first four images and how many it has, opening out in place - that loads on as you scroll, with the NSFW filter. A click opens an image in a viewer, as large as the window, stepping through them all with the arrow keys or the wheel, the prompt and every setting beside it. Sending one back now sets Forge up as it was made - its preset, checkpoint and exactly its text encoders and VAE - which the infotext alone never did, as Forge Neo ignores those lines by default.

- **0.40.12** (build 240) - Sending an image whose checkpoint carries its own text encoders and VAE - an all-in-one Flux.1 or Krea 2 - says so, in a notice naming them: nothing is selected in "VAE / Text Encoder", and Forge uses the checkpoint's. The empty control used to look like a send that had failed. With a problem too, one notice says both.
- **0.40.11** (build 239) - A LoRA stored in diffusers' naming style ("to_k_lora.down.weight") is known as a LoRA, where it was taken for a Checkpoint - so its chip disappeared once it was downloaded, and the Type filter listed it wrongly. Every naming style Forge Neo's LoRA loader reads is now recognised. Scan Disk's dialog gains "Re-evaluate file headers", which reads what every file is again rather than only new or changed ones: tick it once to correct files read before.
- **0.40.10** (build 238) - The LoRA and embedding chips under the prompts no longer change size, so a click meant for one no longer lands on another. A chip shows only its mark and its name; a download fills it from the left, and what it is doing - checking, 37%, adding to library, failed and why - is said on a line under the chips. A missing one is named from the start as its file will be once downloaded, found on Civitai after the send, which does not wait for it: meanwhile the row shows the chips you have and "Loading missing resources...", and the missing ones follow them. A LoRA both of an image's lists name is one chip.
- **0.40.9** (build 237) - Sending a Civitai image to txt2img or img2img takes off the double quotes around a prompt quoted whole, and around a negative prompt: pasted as they were, a Krea 2 model took the whole as one quotation and drew noise. Only a pair around the whole, with no other quote inside - '"a sign" reading "open"' keeps every one. Of 84,677 prompts in one library, 60 were wrapped, 56 of them so.
- **0.40.8** (build 236) - Pin a model in the Model Manager: the 📌 on a card's corner, or beside the ★ in its details, puts it first in the grid whenever it matches the filters, in the grid's own sort - pinning changes the order, never what is shown. A model Civitai does not know is pinned by its file. The card's NSFW rating moves to the top-left, the bookmark star under it. The database gains a table for pins (schema 29): Forge Neo and the original Forge share it, so update both copies of the extension before starting either.
- **0.40.7** (build 235) - Every gallery opens its images in the Generations tab's viewer: a model's Civitai images, its "Your generations", and the Civitai Browser's images, where a click used to open a new browser tab. Each image keeps its own buttons below it and its text beside it, and ← → (or the wheel) run on into the next page. Also: "↓ Previous Position" returns to the image that was sent, from the viewer too; gallery images keep their shape while loading, so the page no longer shifts under a scroll; the Civitai Browser's Resources is the Model Manager's dialog, with Download into the library - a LoRA an image used, without its model; and the NSFW badge names the image's level from R up, where 64,903 of one library's 95,810 Civitai images said "true".
- **0.40.6** (build 234) - A group's tile in the Generations tab no longer offers Send or Delete: Send sent one image as if it stood for the whole group, and Delete took images of any number of generations at once. Its bottom row says what it holds instead - "12 images · 3 generations". A group's batches and images keep both, once it is opened.
- **0.40.5** (build 233) - Sending one of your generations to txt2img or img2img shows its LoRA and embedding chips, as a Civitai image's Send does: the LoRAs Forge loaded for that image, at their weight, and its embeddings, found by their hashes - one gone shows as missing, and downloads if Civitai knows it. A model's "Your generations" cards gain the Resources button and dialog the Civitai image cards have.
- **0.40.4** (build 232) - The database drops the Civitai Browser's old image cache (schema 28), unused since 0.30.3 and never cleared - on one library, 16,807 images and 754 cursors, about 81 MB. The file shrinks only when it is next compacted. Forge Neo and the original Forge share the database: update both copies of the extension before starting either.
- **0.40.3** (build 231) - Rate your own images' NSFW level: "Rate", in the Generations tab and a model's "Your generations", puts a row of levels under every image - and the viewer always shows it. A rating wins over the prompt's level, shows as a plain "X", survives a change of prompt words, and is cleared by clicking it again; an image it hides leaves at once. A batch is rated whole, only the images it shows; a group is not, as one click would misrate images of any prompt.
- **0.40.2** (build 230) - A ⋯ menu on every tile of the Generations tab, and in its viewer, its first item "Show model in Model Manager": the Model Manager tab, the checkpoint's model, opened on the version that file is - found by its exact path (a new "path:" search), where "file:" matches any name containing it. A group whose images come from several checkpoints offers none. The tab's NSFW badge moves to the top-left, out of the menu's way.
- **0.40.1** (build 229) - Group the Generations tab by prompt (as written, or as each image was made), model, LoRA combination, size or day: a tile per group, whatever generations its images are of, with Send and Delete. A batch or a group now opens in a grid of its own, in place of the tab's - a group onto its generations, a batch onto its images, as deep as it goes - under a header with Back (or Esc), which lands where the grid was left; this replaces opening a batch out in place. The Group by dropdown follows the theme, as the filter bars' do.
- **0.40.0** (build 228) - Add the Generations tab: every generation as a tile, 300px high and as wide as its image wants, up to four columns ("Preserve order" keeps every tile one column, strictly newest first), with its date and size; a viewer with ← → and the wheel, Send, Delete and a details panel that folds away; Send and Delete under every tile, a batch deleted whole or an image alone. Your generations' Send, here and in a model's gallery, now switches the preset, selects the recorded checkpoint and patches the modules to exactly those recorded - an SD 1.5 image sent after an Anima one kept the Anima model and encoders.

## 0.30 - Your generations

*28 September 2026*

Every txt2img and img2img result you save is recorded with everything Forge had for it - the prompt as typed, each image's own infotext, every setting and extension's arguments - and filed under each model it used, LoRAs included. A model's gallery gains a second tab beside its Civitai images: your generations with it, a card per generation, which sends its settings back to txt2img or img2img, and can be deleted with or without its files.

- **0.30.6** (build 227) - One click, one download: a model's Download button, in either tab, is disabled from the click until the version is in the library, saying how it is going (Starting, Queued, Downloading, Adding to library) - a second click started the same download again. It comes back if the download is refused, fails or is cancelled.
- **0.30.5** (build 226) - A dismissed download stays dismissed: Dismiss now asks the server to forget it, where it only took it off the page and the next poll brought it back, and the list follows the server's. "Dismiss all" takes every finished download off at once, leaving what is still running.
- **0.30.4** (build 225) - Send to txt2img and img2img patch the VAE / Text Encoder control instead of clearing and refilling it: what is there and needed stays, only what is extra is taken out and only what is missing added, and nothing is touched when nothing differs. Each change is a request of Forge's carrying the whole selection, and after a clear-and-reselect Neo sometimes loaded an Anima model without its VAE while the control showed it. SD and SDXL go the same way, with the image's own VAE. Afterwards Forge's setting is checked, and a notice says so if it does not hold what the image needs.
- **0.30.3** (build 224) - The Civitai Browser shows Civitai's images live instead of from a cache that was never cleared (16,807 images for 911 versions, 825 of them only search samples, with the ratings they had when fetched): each page is fetched from where the last one ended, its banner counts what is loaded, and opening a page takes 0.75 s, its prompt lookups now side by side. The "Only with usable prompts" search checks 8 models at once and pools their prompt lookups - 40 models in 7.2 s and 54 requests, from 13.8 s and 77 - and a lookup that fails no longer drops a model as promptless.
- **0.30.2** (build 223) - Galleries page by what is stored, not by what the filters let through: a page is a fixed slice - 100 by default, set by the new "Images per page" setting - filled from Civitai when the library holds too few, with a "Page N" separator and a note of what it shows and what each filter hid. It used to be 100 images that passed the filters while Civitai was fetched 100 at a time before them, so the two never lined up and a Load More could add images with no page of its own. Load More adds its page below the ones drawn instead of redrawing the gallery, a filter change starts again from page 1, and the Pages mode is gone. The Civitai Browser fetches 100 at a time instead of 10, your generations page the same way, and sync, download and Resync fetch the first page at the page size, up to Civitai's 200.
- **0.30.1** (build 222) - Model cards and both image galleries load Civitai's copy the size they draw an image, not the upload - 86 KB at 450 wide against originals up to 2.9 MB - falling back to the upload if the copy does not load; gallery videos play a copy and show a still until played; a failed image shows its placeholder, which a broken handler never did.
- **0.30.0** (build 221) - Add your generations to each model's gallery, recorded as you generate: a card per generation, one image or a grid of them, Show images for the rest, Send back to txt2img or img2img, Delete with or without the files, Refresh, and the same filters as the Civitai images. A setting turns recording off.

## 0.20 - The settings window

*27 September 2026*

A gear in both tabs opens one window for the extension's settings: grouped, searchable, and showing only what applies. Card sizes come with a preview of real cards, the download folder with an example path, and the text encoders and VAE for each model with a choice of the files installed. It saves to the WebUI's own settings, so the Settings page stays in step.

- **0.20.16** (build 220) - A LoRA an image names without a hash is found by its name as Forge finds it: of several files with the whole name - a .safetensors and a .pt, or two folders - the one Forge would load; the chip said it was missing when two files had the name.
- **0.20.15** (build 218) - When Civitai fails with a server error, what it says goes with it - "Civitai: Image search is temporarily overloaded — please retry. (503)" - instead of "Request failed: Server error: 503".
- **0.20.14** (build 217) - The gallery banner is always there while anything is stored, filtered or not, since it is where the counts are; the Civitai Browser no longer draws it a second time under the list.
- **0.20.13** (build 216) - The gallery banner is a quiet box in the page's own text colour with an amber bar down its left edge, rather than amber throughout: it counts now, rather than warns.
- **0.20.12** (build 215) - The gallery banner says what is stored, what matches the filters and how many of those are shown - it read "Showing 168 of 300" with 100 on screen - and stays at the top as the gallery scrolls; the continuous list marks where each page starts; "300 images downloaded" beside Download More is gone.
- **0.20.11** (build 214) - Sort the Model Manager by how many images each model has stored; a download of more images that fails - Civitai answering 503, the connection dropping - now says so beside the button, in both tabs, instead of looking like a click that found nothing.
- **0.20.10** (build 213) - Galleries arrive a page at a time instead of whole, in both tabs; images a download brings no longer show past the NSFW switch; "Download More Images" brings new images on the first click after a bulk sync, which now keeps where Civitai's next page starts; a note beside the button says how many came and what hid them; a sync that fails to fetch a gallery no longer empties it.
- **0.20.9** (build 212) - Download to <name>.partial and rename it only once whole and its SHA-256 checked, never over a file that appeared meanwhile; a failed download removes only its own .partial, never a file under a model's name.
- **0.20.8** (build 209) - Remove the Civitai Browser's Resume button, the search positions it saved in the browser, and Search's right-click that cleared them.
- **0.20.7** (build 208) - Scan Disk reads the embeddings folder, and no longer forgets every embedding a download added; a file already on disk that is the one Civitai lists is added to the library instead of refusing the download; every failed download says why - on its chip, in the browser console and in the WebUI's.
- **0.20.6** (build 207) - Find an image's LoRAs and embeddings by file name when no sync has identified the file yet, checking its hash where the image gives one; chips now show by colour and mark whether each is in the library, downloadable or not available, filled when a prompt holds it, with a key underneath.
- **0.20.5** (build 206) - Draw both tabs' model cards, page strips and grids with one renderer; the Civitai Browser's Prev and Next now show disabled at the ends, its type badge is escaped, and a long name is no longer cut inside a character like &.
- **0.20.4** (build 205) - Show how far judging stored images again has got after an NSFW setting changes - from the settings window or the WebUI's Settings page - and what changed.
- **0.20.3** (build 203) - Show the extension's version beside the settings gear, linking to this changelog.
- **0.20.2** (build 202) - Test the Civitai API key from the settings window.
- **0.20.1** (build 201) - Choose each model's text encoders and VAE from what is installed.
- **0.20.0** (build 200) - Add a settings window to both tabs, kept in step with the Settings page.

## 0.19 - Every version of a model

*26 - 27 September 2026*

The details panel lists every version Civitai has for a model, not only those on disk, and any of them can be downloaded from there. The list is kept from each sync, so it costs no extra requests.

- **0.19.4** (build 199) - Open every model's gallery as the settings say, the same in both tabs.
- **0.19.3** (build 198) - Let the user choose the trained NSFW model or the word list, and say which is in use.
- **0.19.2** (build 197) - Wait for Forge to finish a preset change before sending an image's settings.
- **0.19.1** (build 196) - Ship the NSFW prompt model trained on Civitai, which judges a new library better.
- **0.19.0** (build 195) - Show every version of a model in the Model Manager, and download the rest there.

## 0.18 - A trained model judges prompts

*26 September 2026*

A model trained on a pull of Civitai reads each image's prompts and the resources it used, and raises the explicit ones Civitai rated PG or PG-13 to X. How far it goes is a setting, and the word list still applies alongside it.

- **0.18.1** (build 194) - Train the NSFW prompt model from a pull of Civitai, and read more of each image.
- **0.18.0** (build 193) - Judge prompts with a trained model as well as the word list.

## 0.17 - Works in the original Forge

*25 - 26 September 2026*

The extension runs in the original Forge as well as Forge Neo, and the two can share one database. What only Neo has is skipped there rather than failing.

- **0.17.2** (build 191) - Delete from the details header, one version or all of them.
- **0.17.1** (build 188) - Finish a download before calling it complete, without hashing it again.
- **0.17.0** (build 187) - Work in the original Forge as well as Neo.

## 0.16 - LoRA and embedding chips

*25 September 2026*

Send to txt2img lays an image's LoRAs and embeddings out as chips under the prompts, to put in the prompt or take out with a click. One you do not have downloads straight into your library.

- **0.16.1** (build 186) - Keep an image in every gallery that shows it.
- **0.16.0** (build 185) - Put an image's LoRAs and embeddings under the prompts as chips, and download them in place.

## 0.15 - Video models

*25 September 2026*

A Wan text-to-video image is sent as a video, with its frame count, and an image-to-video one goes to img2img starting from the video's first frame, instead of failing in txt2img.

- **0.15.1** (build 184) - Send an image-to-video model to img2img, starting from the video's first frame.
- **0.15.0** (build 183) - Send a Wan text-to-video as a video, and refuse image-to-video in txt2img.

## 0.14 - Explicit prompts judged

*25 September 2026*

An image Civitai rates PG or PG-13 whose prompt uses an explicit word counts as X everywhere: grid previews, both galleries and the SFW filters. The words ship with the extension, and more can be added in the settings.

- **0.14.3** (build 182) - List the library's own base models in the Model Manager filter.
- **0.14.2** (build 180) - Arrange the Civitai Browser filters by how often they are used.
- **0.14.1** (build 179) - Look up only the shown cards' images when loading the grid.
- **0.14.0** (build 178) - Treat a PG image with an explicit prompt as X.

## 0.13 - Send to txt2img sets Forge up for the model

*24 September 2026*

Sending an image from Flux, Qwen-Image, Wan or another newer model switches Forge to that model's UI preset and selects the text encoders and VAE it needs. They are picked from what is installed by what each file is, not by its name.

- **0.13.9** (build 177) - Forget only files gone from disk, and what only they kept.
- **0.13.8** (build 176) - Read version-format sidecars, and keep scanning past a file that fails.
- **0.13.7** (build 175) - Set Forge up for the model an image was made with, not its gallery's.
- **0.13.6** (build 174) - Filter and label Model Manager models by what their files are.
- **0.13.5** (build 173) - Identify every model file from its own contents.
- **0.13.4** (build 172) - Let each preset's text encoders and VAE be named in the settings.
- **0.13.3** (build 171) - Only count a T5 or UMT5 file Forge can load.
- **0.13.2** (build 170) - Index GGUF and .sft model files.
- **0.13.1** (build 169) - Set Forge up for the model before Send to txt2img sends the image.
- **0.13.0** (build 168) - Pick the text encoders and VAE a model needs from what is installed.

## 0.12 - Model files identified from their contents

*24 September 2026*

Each model file's header is read to tell what it is - checkpoint, LoRA, VAE, text encoder and more - and which model it is for, with Forge's own detector for checkpoints. The Type filter and labels use that rather than Civitai's type, which is whatever the uploader chose.

- **0.12.0** (build 167) - Read each model file's architecture from its own header.

## 0.11 - Only models with SFW images

*23 - 24 September 2026*

Leave out any model whose latest version's first example images include anything above PG-13 - which Civitai's own NSFW switch lets through. In the Civitai Browser first, then the Model Manager.

- **0.11.16** (build 166) - Caption the Civitai Browser's checkpoint filter "Checkpoint Type".
- **0.11.15** (build 165) - Rename "Only with SFW images" to "Only Show Models with SFW images".
- **0.11.14** (build 164) - Make the Resources button count what its panel lists.
- **0.11.13** (build 163) - Load card videos as a resized MP4, and card images as uploaded.
- **0.11.12** (build 162) - Keep a safe preview on every card when NSFW is hidden.
- **0.11.11** (build 161) - Show the same model preview in both tabs for the same NSFW choice.
- **0.11.10** (build 160) - Make the sync dialog's request lines add up to its total.
- **0.11.9** (build 159) - Keep stored prompts when a gallery is replaced.
- **0.11.8** (build 158) - Keep the order Civitai gives a version's images in.
- **0.11.7** (build 154) - Split the Civitai Browser's options by who applies them.
- **0.11.6** (build 153) - Show the Civitai Browser's chosen tag as a chip, and suggest tags at once.
- **0.11.5** (build 152) - Stop the file size filter stretching across the search row.
- **0.11.4** (build 151) - Start every Civitai Browser search at its own pages.
- **0.11.3** (build 150) - Add a setting to fill every page with "Only with SFW images".
- **0.11.2** (build 149) - Leave out models with no images from the Civitai Browser's SFW filter.
- **0.11.1** (build 148) - Add "Only with SFW images" to the Model Manager.
- **0.11.0** (build 147) - Add "Only with SFW images" to the Civitai Browser.

## 0.10 - File size filter

*23 September 2026*

Minimum and maximum download size, in GB, for Civitai Browser searches, applied to the file a download would fetch. Civitai's search cannot filter on size.

- **0.10.0** (build 146) - Filter the Civitai Browser by file size.

## 0.9 - Trained or merged checkpoints

*21 - 23 September 2026*

Filter the library's checkpoints by whether they were trained or merged. Civitai accepts that as a search filter but never returns it, so it is worked out from which filtered searches each model appears in.

- **0.9.41** (build 145) - Sort names without regard to case.
- **0.9.40** (build 144) - Page the Model Manager by its setting, and keep its rows even.
- **0.9.39** (build 143) - Show 20 models per page in the Civitai Browser by default.
- **0.9.38** (build 142) - Keep the Civitai Browser's rows even as the window is resized.
- **0.9.37** (build 141) - Default the Model Manager's NSFW filter to every level, Unknown and below.
- **0.9.36** (build 140) - Put both gallery filters in one banner, with numbers that add up.
- **0.9.35** (build 139) - Make every gallery switch read "Show ..." with a count, in both tabs.
- **0.9.34** (build 138) - Give the Civitai Browser's prompt banner a switch, as its NSFW one has.
- **0.9.33** (build 137) - Stop a slow Civitai call from stalling the whole WebUI.
- **0.9.32** (build 136) - Put the Civitai Browser's NSFW switch in the banner, as in the Model Manager.
- **0.9.31** (build 135) - Only delete files the library itself recorded.
- **0.9.30** (build 134) - Stop Civitai content from running as script in the WebUI.
- **0.9.29** (build 133) - Resolve an image's resources, then show each of them once.
- **0.9.28** (build 132) - Make the resources actions an ordinary table cell again.
- **0.9.27** (build 131) - Centre the resource buttons in a row that wraps.
- **0.9.26** (build 130) - Put the two header actions on the same button.
- **0.9.25** (build 129) - Hide example images that carry no prompt to read.
- **0.9.24** (build 128) - Let the example images run as one list, with a button to show more.
- **0.9.23** (build 127) - Let the Model Manager hand a model to the Civitai Browser.
- **0.9.22** (build 126) - Declare the preview helpers where their callers can see them.
- **0.9.21** (build 125) - Ask to show NSFW in the preview, rather than to hide it.
- **0.9.20** (build 124) - Put Previous Position beside Load Models, and Load Models last.
- **0.9.19** (build 123) - Wire the Resume button once the markup actually exists.
- **0.9.18** (build 122) - Offer Resume whenever there is a page to resume to.
- **0.9.17** (build 121) - Stop the sort control reading "Most Download...".
- **0.9.16** (build 120) - Lay the browser's options across, and put its actions on their own row.
- **0.9.15** (build 118) - One filter bar, not two that look alike.
- **0.9.14** (build 117) - Take the descender gap out from under the tag box.
- **0.9.13** (build 116) - Let the Civitai Browser's inputs use the shared control box.
- **0.9.12** (build 115) - One height for every control in a filter group.
- **0.9.11** (build 114) - Give Sort By the width the preview toggle was not using.
- **0.9.10** (build 113) - Split the filters into one visible row and an Advanced disclosure.
- **0.9.9** (build 112) - Put the button colour past Gradio's preflight reset.
- **0.9.8** (build 111) - One definition for every button, and pin the margin Gradio adds.
- **0.9.7** (build 110) - Stop a downloaded checkpoint reporting a sync error it did not have.
- **0.9.6** (build 102) - Stop browsers serving a year-old copy of the shared module.
- **0.9.5** (build 101) - Put the API key banner back after Gradio redraws the page.
- **0.9.4** (build 100) - Warn about the missing API key on the Civitai Browser tab too.
- **0.9.3** (build 99) - Wait for both halves of the API key banner, rather than assuming an order.
- **0.9.2** (build 98) - Show the API key banner, rather than deciding it too early to matter.
- **0.9.1** (build 97) - Say so when there is no Civitai API key.
- **0.9.0** (build 96) - Filter the library by trained or merged checkpoints.

## 0.8 - The sync dialog

*21 September 2026*

Sync asks which models to refresh - all of them, the current search results, or those not synced in a chosen time - and how much of each, and says how many requests that will take before it starts.

- **0.8.20** (build 95) - Apply the no-clobber rule to civitai_models too.
- **0.8.19** (build 94) - Have Scan Disk say what it will do before doing it.
- **0.8.18** (build 93) - Do not leave Image prompts ticked while it is unreachable.
- **0.8.17** (build 92) - Put the two ways of updating the library next to each other.
- **0.8.16** (build 91) - Stop a thin sidecar emptying the row it lands on.
- **0.8.15** (build 90) - Let a sync see the disk, so Refresh DB is no longer the only thing that does.
- **0.8.14** (build 89) - Make identifying a scope, so Include only ever means what data to fetch.
- **0.8.13** (build 88) - Hold the scope at all models while identifying files.
- **0.8.12** (build 87) - Say how many files are unmatched, and stop calling it re-identifying.
- **0.8.11** (build 86) - Count requests instead of promising minutes.
- **0.8.10** (build 85) - Add a download-date scope, and forget the sync times that were never real.
- **0.8.9** (build 84) - Only offer to sync the search results once there are some.
- **0.8.8** (build 83) - Stop a Refresh DB claiming every model was just synced.
- **0.8.7** (build 82) - Give the window dropdown's option list something opaque to sit on.
- **0.8.6** (build 81) - Stop the dialog colouring its panels from a variable that is white.
- **0.8.5** (build 80) - Draw the sync dialog's dropdown rather than letting the browser.
- **0.8.4** (build 79) - Make the sync dialog's window dropdown follow the theme.
- **0.8.3** (build 78) - Read each model once to hash it, not twice.
- **0.8.2** (build 77) - Stop a metadata sync throwing away the hashes it does not recognise.
- **0.8.1** (build 76) - Let a database be created from nothing again.
- **0.8.0** (build 75) - Ask what to sync before syncing it, and say what it will cost.

## 0.7 - Metadata-only sync

*21 September 2026*

Refresh the library's Civitai data - descriptions, tags, stats, licences and example images - without reading every file again to hash it. Only identifying new files needs the hashing.

- **0.7.11** (build 74) - Let a sync say how much of the library it covers, and what that costs.
- **0.7.10** (build 73) - Fill the generation-data batches, and stop asking for half of them.
- **0.7.9** (build 72) - Stop Unknown from outranking XXX.
- **0.7.8** (build 71) - Point the post-download sync at the database package.
- **0.7.7** (build 68) - Read every field Civitai names a VAE in.
- **0.7.6** (build 65) - Judge NSFW in one place, and believe browsingLevel.
- **0.7.5** (build 64) - Restore the browse cache delegate's name.
- **0.7.4** (build 62) - Remember when Civitai did not know a file, and stop re-reading it.
- **0.7.3** (build 61) - Make the licence filters four-valued dropdowns.
- **0.7.2** (build 60) - Group the Model Manager's action buttons and right-align them.
- **0.7.1** (build 59) - Poll metadata sync progress on an interval, not once.
- **0.7.0** (build 58) - Add metadata-only sync, which skips the hashing.

## 0.6 - Show in Model Manager

*20 - 21 September 2026*

Jump from a model in the Civitai Browser to the same model in your library. The Model Manager's search also takes exact lookups: model:, version:, hash: and file:.

- **0.6.15** (build 57) - Show thumbs up/down on cards, and always offer the NSFW toggle.
- **0.6.14** (build 56) - Select a VAE with mousedown, which is what the list listens for.
- **0.6.13** (build 55) - Find the VAE control on classic Forge too, not just Neo.
- **0.6.12** (build 54) - Clear the VAE on send-to-txt2img instead of leaving the last one.
- **0.6.11** (build 53) - Let a download pick which of a version's files it wants.
- **0.6.10** (build 52) - Name the file the download button will actually fetch.
- **0.6.9** (build 51) - Filter checkpoints by build, pick the primary file, refuse paid versions.
- **0.6.8** (build 50) - Fill the Civitai Browser dropdowns from Civitai's own enums.
- **0.6.7** (build 46) - Refresh the WebUI model list after a download.
- **0.6.6** (build 44) - Stop scans and re-syncs from erasing per-version state.
- **0.6.5** (build 43) - Record when a model was downloaded, not when its sync finished.
- **0.6.4** (build 42) - Sort grouped models by the newest version acquired, not the shown one.
- **0.6.3** (build 41) - Sort models by when they were acquired, by default.
- **0.6.2** (build 40) - Show a downloaded model as owned once its sync finishes.
- **0.6.1** (build 37) - Move "Show in Model Manager" to the details header.
- **0.6.0** (build 36) - Add "Show in Model Manager" jump from the Civitai Browser.

## 0.5 - Licence filters

*20 September 2026*

Filter the library by what a model's licence allows: commercial use, derivatives and relicensing. The details panel's example images can be filtered by NSFW level too.

- **0.5.0** (build 35) - Add license filters and NSFW image filtering to Model Manager.

## 0.4 - Only models with usable prompts

*20 September 2026*

A Civitai Browser option that keeps only models whose example images carry a prompt and settings worth reusing. Civitai cannot filter on that, so each model's images are checked here, and results stream in as they are found.

- **0.4.2** (build 34) - Stream Civitai Browser results as models are found.
- **0.4.1** (build 33) - Speed up Civitai browsing with a higher rate limit and parallel checks.
- **0.4.0** (build 32) - Add usable-prompt filter to Civitai Browser.

## 0.3 - The Civitai Browser tab

*7 January 2026 - 20 September 2026*

A second tab for searching Civitai by type, base model and tag, with the models you already have marked. Downloads run with progress and land in the folder for their model type.

- **0.3.10** (build 31) - Fix downloaded models never reaching the database.
- **0.3.9** (build 30) - Find model directories on both Forge and Forge Neo.
- **0.3.8** (build 29) - Restore image generation metadata from Civitai.
- **0.3.7** (build 28) - Scroll to top before load-more image page switch.
- **0.3.6** (build 27) - Calibrate first-load model page size before loading.
- **0.3.5** (build 26) - Scroll to image list top before page-number navigation.
- **0.3.4** (build 25) - Add top image pagination controls in image galleries.
- **0.3.3** (build 24) - Optimize model listing and fix first-load filter defaults.
- **0.3.2** (build 23) - Update model manager filtering, pagination, and data handling.
- **0.3.1** (build 22) - Fix duplicate images when loading more in Model Manager.
- **0.3.0** (build 21) - Add Civitai Browser feature with download support.

## 0.2 - One database, shared between WebUIs

*28 - 29 December 2025*

The database can be kept anywhere, so several WebUI installs - Forge Neo and the original Forge, say - can share one library and its Civitai data.

- **0.2.5** (build 20) - Add multi-hash support and cursor-based image pagination.
- **0.2.4** (build 19) - Add Blocked level to NSFW filter dropdown.
- **0.2.3** (build 18) - Improve NSFW dropdown behavior in max mode.
- **0.2.2** (build 17) - Change multi-select NSFW filter to exact match.
- **0.2.1** (build 16) - Fix NSFW filter: handle 'None' level for PG images.
- **0.2.0** (build 15) - Add custom database path setting.

## 0.1 - The Model Manager tab

*25 - 28 December 2025*

The first version: every model on disk in a grid with its Civitai preview, filters and sorting, and a details panel with the model's Civitai data and example images. Sync fetches the metadata and images, and Send to txt2img applies an example image's settings.

- **0.1.12** (build 14) - Add scroll-to-top button.
- **0.1.11** (build 13) - Refactor database layer and add major improvements.
- **0.1.10** (build 12) - Add QOL improvements and fix ADetailer/pagination issues.
- **0.1.9** (build 10) - Add API endpoint for samplers/schedulers.
- **0.1.8** (build 9) - Split combined sampler+scheduler format dynamically.
- **0.1.7** (build 8) - Improve send to txt2img and image display.
- **0.1.6** (build 7) - Add back checkpoint and VAE loading to send to txt2img.
- **0.1.5** (build 6) - Rewrite send to txt2img using paste button approach.
- **0.1.4** (build 5) - Add "Show All" button to display full image metadata in modal.
- **0.1.3** (build 4) - Fix checkpoint path: preserve Windows backslashes.
- **0.1.2** (build 3) - Fix send to txt2img: add VAE support, fix undefined variable.
- **0.1.1** (build 2) - Add full model data fetch and partial data detection.
- **0.1.0** (build 1) - Model Manager extension for SD WebUI Forge.
