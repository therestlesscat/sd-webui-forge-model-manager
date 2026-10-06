# Changelog

Every version of the extension, newest first. A version is MAJOR.MINOR.PATCH.BUILD:
a minor version is a feature that stands on its own, a patch is any other change you
can see, up to the next minor version, and the build is the commit's place in the
repository's history. A change that only touches tests, documentation or the code's
structure keeps its version and moves the build on, and is not listed here.

## 0.50 - A queue for your generations

*5 October 2026*

Set up a generation, and press Queue instead of Generate: it is kept as a task, to run later. The new Queue tab runs the tasks one at a time, each with its own checkpoint, VAE and text encoders, while you go on working - and shows them, loads one back into its tab, retries and deletes them. The Generations tab gains a search, which also shows the images a task made.

- **0.50.15** (build 391) - The Queue tab's lists draw again only the tasks that changed; the rest stay as they are on screen.
- **0.50.14** (build 390) - Show hidden, beside History's Select, brings back the tasks Clear history hid, marked Hidden among the rest, to retry, delete or unhide - one at a time or several selected. Clear history's question counts only what it hides.
- **0.50.13** (build 389) - Run next runs a waiting task before the others, alone or several selected: after the running task, or at once when the queue is stopped or paused. A stopped queue runs only those and stops again; a paused one stays paused. A task already next in line has Run next greyed out.
- **0.50.12** (build 388) - A waiting task can be cancelled, alone or several selected: it moves to History as Cancelled, where Retry queues it again.
- **0.50.11** (build 387) - The queue is ready. A note on the Queue tab says what it does, and one on the Generations tab tells of its search. Two WebUIs sharing one database are told to update the other copy before starting it. The queue's folder setting says it keeps ControlNet's images too, not only img2img's.
- **0.50.10** (build 386) - Pause says "Pausing…" while the running task finishes, and offers Resume only once the queue has paused.
- **0.50.9** (build 385) - The running task in the Queue tab has a bar along its row, showing how far along it is.
- **0.50.8** (build 384) - The queue can be turned off, as Your generations can: in the settings window's new Queue section, or Settings -> Model Manager. Off, the Queue tab and the Queue buttons are hidden at once, and a running queue stops. The tasks are kept.
- **0.50.7** (build 383) - Queued tasks can be retried, with the first run's seed or a random one, and deleted, with the images they made or without. Select ticks several at once. Clear history hides the ended tasks.
- **0.50.6** (build 382) - A click on a queued task shows everything it holds. Load to UI sets txt2img or img2img up with it, checkpoint and VAE included, to change it or run it by hand. The Queue tab shows no images: Show images opens the Generations tab on the ones a task made.
- **0.50.5** (build 381) - The Generations tab has a search. Every word must be in an image's prompt or negative prompt; a quoted phrase counts as one word. task:17 shows the images task 17 of the queue made.
- **0.50.4** (build 380) - The Queue tab shows the queue: what it is doing, with Start, Pause, Resume and Stop; and the Active and History lists, each task with what it asks for and the first images its run made. The lists follow the queue as tasks start and end.
- **0.50.3** (build 379) - The queue can now be driven and read: its state, Start, Stop, Pause and Resume; the Active and History lists, a task's details and the images its run made; Retry, Delete and Clear history. The Queue tab that uses them comes next.
- **0.50.2** (build 378) - Queued tasks can now be run: one at a time, in the order queued, each as Generate would run it, with the checkpoint and VAE it was queued with. A task that fails or is interrupted ends alone, and the queue goes on. Nothing starts the queue yet: its controls come next.
- **0.50.1** (build 377) - A Queue button beside Generate, in txt2img and img2img, keeps the generation as a task, with its images, and generates nothing. A Queue tab appears before Generations; it will list and run the tasks.
- **0.50.0** (build 376) - The database moves to v34, to keep queued generations. Two WebUIs sharing it must both be updated.

## 0.48 - Sync reads your model folders

*4 October 2026*

Every sync now starts by reading your model folders, whichever models it refreshes: files you have added join the library and are read for what they are, files you have deleted leave it, and every new file is looked up on Civitai - not only in a force sync. The sync dialog says how many files that is, and how big, before you start. Scan Disk is gone, and a model's details come from Civitai alone: a .civitai.info beside a file is read only for a model Civitai no longer has.

- **0.48.6** (build 372) - A model's details are stored before its images are fetched: when Civitai cannot serve the images, the model keeps its fresh details and its stored gallery, where it used to lose its details too - 21 files of one force sync did. What Civitai fails on is tried again at the end of the sync, more patiently - six retries, waiting 2, 4, 8, 8, 8 and 8 seconds: the whole model where Civitai could not say what a file is, its images alone where only they failed, and the log says each. What fails twice is an error. A refused API key stops a lookup at once.
- **0.48.5** (build 371) - A sync shows its log: every line the extension writes to the console while it runs - the walk, each file looked up, each gallery, every error in red - in a panel in place of the grid and its tabs. Hide brings the grid back, and Log the panel; it stays once the sync has ended. While a sync reads your model folders, before it knows how many models it will sync, its bar says "Reading your model folders: 120/1576" and the file being read, where it said "Syncing: 0/0". Cancel says what it is waiting for: the button turns to "Cancelling...", the bar and the status line say the files in progress are finishing, the log names them and says as each is done, and the sync ends as "cancelled".
- **0.48.4** (build 370) - A sync reads a file for its SHA-256 first, with the AutoV1 and AutoV2 that come with it, and asks Civitai by those; AutoV3, BLAKE3 and CRC32 are read only when none of them is known. Found by its SHA-256, a file takes the other hashes Civitai lists for it, as a download does. Identifying files runs about twice as fast where the CPU, not the drive, sets the pace (3.66 GB/s against 1.90 here, on NVMe); a file Civitai does not know is read twice. The "Sync: Hashing threads" setting says, per kind of drive, how many to use; its default stays 4.
- **0.48.3** (build 369) - Scan Disk is gone: every sync reads your model folders first (0.48.0), and its two boxes are in the sync dialog. "Move files into their type's folder (N)" counts the files it can move - not those whose name is taken in their folder - and says what moving does, and which files, only once it is ticked. The toolbar's button is now just "Sync", on the left of the row without a box around it, and its Cancel shown as the other buttons are, where it had a display of its own; while a sync runs, Sync stays at full strength beside Cancel instead of dimming. Notes that asked to run Scan Disk now ask for a sync with "Read every file's header again" ticked, and open the sync dialog so. A .civitai.info is no longer read as a source for a model Civitai has: Scan Disk read every one, and wrote its hashes over the file's own and its showcase into the version's NSFW level (#104). Levels it stored stay until a sync refreshes them; nothing has to be synced again.
- **0.48.2** (build 368) - The Sync with Civitai dialog, and the one asking before an image is deleted, are wider: up to half the window, and 800 px at most, where they stopped at 420 px.
- **0.48.1** (build 367) - A file's hashes are read from it once, and kept with its size and date then: a model's Sync asks Civitai with them while the file is unchanged, instead of reading it again. A force sync still reads every file again, and any sync reads again a file changed since. The hashes of a file Civitai does not know are kept too; they used to be dropped. Civitai not answering no longer marks a file "not on Civitai", which every later sync skipped: only Civitai saying so does. A .civitai.info is read in one case only - Civitai knows neither the file nor the model it names - and the file is then filed as it says, at its version's own level. The details panel no longer fills in an unidentified file from its .civitai.info, and a model's other versions, if never listed, are asked of Civitai instead of read from .civitai.info files. The database moves to v33: two WebUIs sharing it must both be updated.
- **0.48.0** (build 366) - Every sync starts by reading your model folders, as Scan Disk does: a new file gets its place in the library and its header read, a changed one its new size, and a file gone from disk is forgotten, with the models and images only it kept. Every sync then reads each new file in full and asks Civitai what it is, where only a force sync did; the dialog's estimate says how many files and how many GB. The dialog has a Files section, above the estimate: "Read every file's header again", and "Move files into their type's folder", which lists the files first, as Scan Disk's does. Both start unticked every time.

## 0.47 - Send sets up the gallery's model

*4 October 2026*

Send to txt2img from any gallery sets Forge up for the model the gallery is of, and for the checkpoint the image was made with. From a LoRA's, a VAE's or an embedding's gallery, the image's checkpoint is loaded, where Forge used to keep whatever it had; one your library lacks stops the send and opens the image's Resources, to download it there. From a VAE's or a text encoder's gallery, that file is the one selected.

- **0.47.6** (build 363) - In the Generations tab's Select mode, an image no longer shows the magnifying-glass cursor: a click there ticks it, and the cursor and the image's title (and a batch's) say "Select". Out of Select mode they are as before.
- **0.47.5** (build 362) - A click around an image in the viewer closes it as the mouse button goes down, in every gallery. It used to stay on screen until the button was released.
- **0.47.4** (build 361) - In the Civitai Browser, Esc in the tag box with suggestions showing closes the suggestions alone; the next Esc closes the open model. One Esc used to close both.
- **0.47.3** (build 354) - When Send stops for a missing checkpoint, the Resources dialog it opens has a Send to txt2img of its own. It stays greyed out, saying why, until the checkpoint can be loaded; once a download lands, it is asked again, and works without closing the dialog. A checkpoint Forge does not list yet gets Forge's checkpoint list refreshed.
- **0.47.2** (build 353) - Send to txt2img from an upscaler's gallery puts that upscaler in Hires fix's "Upscaler", by the name Forge lists it under, with the image's checkpoint as from any other gallery; Hires fix itself stays on or off as the image had it. An upscaler Forge does not list - in a folder this WebUI does not load, or added since Forge started, as Forge reads its upscalers once - is said, and Hires fix keeps the image's.
- **0.47.1** (build 352) - An image that does not say which checkpoint it was made with - no model name, no model hash, no checkpoint among its resources - cannot be sent from a gallery that is not a checkpoint's: its Send to txt2img is greyed out, on the card and in the viewer, and says why. From a checkpoint's gallery it sends as before, with that checkpoint.
- **0.47.0** (build 351) - Send to txt2img from a gallery that is not a checkpoint's - a LoRA's, a VAE's, an embedding's - loads the checkpoint the image was made with, where it used to keep whatever Forge had loaded. One your library lacks stops the send: the image's Resources open, saying which, to download it there; one in a folder this WebUI does not load is said, with where it is, and nothing is moved. From a VAE's or a text encoder's gallery, that file is selected in "VAE / Text Encoder" in place of the one Send would have picked, the rest picked as before.

## 0.46 - One version, its files under it

*3 October 2026*

A Civitai version is one version in the library, however many of its files you have - an fp16 and an fp32, a `.safetensors` and a `.pt`, the same file in two WebUIs' folders. Each file used to be a version of its own, with its own copy of the version's details, and the copies drifted apart.

- **0.46.0** (build 349) - A version with several files is one version: one pill in a model's details, and counted once on its card and by the "versions" filter. Under its pill, a table of its files says what each is - type, name, size, date, folder, its file id on Civitai - which one Send uses, and deletes one alone; there is nothing to pick, as the galleries are the version's. A sync fetches its gallery once, not once per file, and the sync dialog costs it once; Load More reads where the version's gallery stopped, which the copy of one file could have lost. Showing a generation's model from the Generations tab opens the file it used. The database changes shape on the first start, after a backup beside it; a WebUI sharing the database needs this version too - an older copy can no longer open it, and from now on a copy older than its database says so rather than use it.

## 0.45 - I'm feeling lucky

*2 October 2026*

The Civitai Browser can show you models you would never have searched for. Tick "I'm feeling lucky" and Search becomes Draw: a page of models picked at random from all of Civitai, every model your filters allow as likely as any other - the obscure as often as the famous.

- **0.45.7** (build 347) - Light mode, and colours in both. The filter boxes, dropdown panels, Tag suggestions and version pills were dark in light mode, and gallery cards, Generations tiles, the model grid's image wells and several panels grey or black; they follow the theme now, and dark mode is as it was. A ticked checkbox in the three tabs is filled, where light mode showed it empty. Text the WebUI's own styles had overridden - the date and count on a Generations tile, badges on images, trigger words, type and base-model badges, resource labels, chips, the settings window's warnings - shows its own colour, in dark mode too. View on Civitai in a model's header is a button, the same as Sync and Delete beside it.
- **0.45.6** (build 346) - Refreshing a model's images no longer cuts its gallery back to the first page without asking. With Images ticked, the sync dialog offers "As many as each model has now" - chosen to start with - or "First 100 images per model", each with its request count, and says above Start how many stored images the first would delete, that they can still be seen with Load More, and that either may bring other images than these; a force sync offers the same choice. The Sync button in a model's header asks the same, and replaces Resync Images, which is gone. View on Civitai is in the header too, for the version shown. "Example images" in the sync dialog is now "Images".
- **0.45.5** (build 345) - A gallery loading from Civitai says what it waits on: a turn at the request rate, a retry in Civitai's own words with the seconds until it, Civitai limiting requests, a timeout or a lost connection, and each slow step - the images, then their prompts. Opening a model or changing a switch says it over the gallery, Load More under its button, Resync Images on the status line; both tabs alike.
- **0.45.4** (build 344) - The image viewer says an image's id, for your own generations: an Image ID field in the Generations tab, and at the end of the date line in a model's Your generations - to name one image when reporting what it did.
- **0.45.3** (build 343) - The chips under the prompt find a LoRA as Forge does. A prompt that names a LoRA by its alias - the name in its metadata, such as the training_… names Civitai's trainer gives, which Forge puts in a prompt when "Alias from file" is chosen - finds the file without a hash, as long as no other file shares the alias. A LoRA in a folder the running WebUI does not load LoRAs from - another WebUI's, in a shared library - is no longer shown as in the library. Send from your own generations renames a LoRA the prompt names otherwise than its file to the file, as a Civitai image's Send does, and neither Send pastes the image's Lora hashes any more: Forge's paste renamed each LoRA they list to its alias, so the prompt and its chips named one LoRA two ways and the chip was not lit. A LoRA downloaded from its chip has its tag in the prompt renamed to the file too. Scan Disk reads each LoRA's alias: run it once.
- **0.45.2** (build 342) - A `.civitai.info` that names no version - an error or a stub another tool left beside a file - no longer counts as Civitai data. Such a file was shown as identified and never looked up by a sync, and a stub with a model id wrote its name over that model's. Scan Disk now reads it as no sidecar and puts right the rows earlier scans wrote, and a sync looks the file up.
- **0.45.1** (build 340) - After Send to txt2img, looking up what an image's missing resources are called asks Civitai about at most 20 unknown hashes at a time, as the Resources dialog does, and the chips ask about the rest in rounds. An image naming hundreds of hashes no longer holds every other Civitai request up for minutes.
- **0.45.0** (build 339) - "I'm feeling lucky", beside Save Search in the Civitai Browser. It keeps the filters Civitai applies itself - Type, Checkpoint Type, Base Model, Tag, Period and Include NSFW models - and greys out the rest while it is ticked: the search text, which Civitai's search cannot combine with a draw, the sort, and the post-processing options, which would cost a request per model. Each Draw is a fresh page. A draw asks Civitai about random model numbers, thousands in one request, so it usually takes one or two requests; when few models match - Checkpoint and Week, say - it lists them all and picks from those, and the status line says how many there were.

## 0.44 - Sounder foundations

*1 October 2026*

A review of how the extension's parts depend on each other, worked through one finding at a time. It found bugs that lose or misstate what your library knows, and code written twice that had begun to disagree; each version below fixes one. Most of the rest is out of sight: a rule kept in one place instead of several, so the next fix lands once.

- **0.44.29** (build 338) - Notes at the top of the tabs say what 0.44 asks of you after updating: run Scan Disk once with "Re-evaluate file headers" (it now walks every folder a download can go to, tells ControlNets from checkpoints, and offers to move files sitting in another type's folder) - which retires the 0.40.11 note asking the same. Three more say what you might otherwise wonder at: a download filed by what its file is, browsing that waits its turn while a sync runs, and the Generations tab's own setting for hiding explicit images.
- **0.44.28** (build 334) - Scan Disk's "Move files into their type's folder" keeps a file and its row together when the folder still had a row for a file of that name deleted outside the extension. The file was moved but its row could not follow, and the next scan forgot it: its pin, download date and generations were lost. That row is now replaced, and its pin and generations kept with the moved file's. If the database refuses the move, the file is put back rather than left where no row names it.
- **0.44.27** (build 333) - Closing Show All or Resources opened from the image viewer leaves the page under the viewer held still. It let it scroll again - its scrollbar back behind the viewer - in the Model Manager since the windows were added, and in the Civitai Browser since 0.44.18 gave both tabs one Show All. The page is now held while anything is open over it, and let go with the last.
- **0.44.26** (build 332) - A page reloaded by "Apply and restart UI" works as one page again. It could load before the extension's routes were added, and each tab then ran its own copy of the shared code for the rest of the session: a download started in one tab missing from the other's panel, notes dismissed per tab, the update check run three times. The tabs now wait the moment until the Model Manager's API answers.
- **0.44.25** (build 331) - A file the library holds under one spelling of its path is found under any other in every step, not only when it is stored. Since 0.44.8 a file a scan or sync found under a differently-cased path - two WebUIs sharing the database with their folder options typed differently - stayed one entry, but the sync hashed it and asked Civitai about it again on every run, "not on Civitai" never stuck, Scan Disk read its header every time without keeping what it read, and a download's date could be lost. No file in this library is affected.
- **0.44.24** (build 330) - Download in the Resources dialog, and on a missing LoRA's chip under a sent prompt, follows a version that is already downloading - started in the Civitai Browser, say - to Installed. Since 0.44.18 it said "Failed: Already downloading" and stayed so after the download landed; and a finished download still in the list could not be downloaded again after its model was deleted. Asked again for a version on its way, the download queue now answers the download it has instead of starting it over.
- **0.44.23** (build 329) - A ControlNet is a ControlNet: since 0.44.1 a scan typed ControlNets, Control-LoRAs and ControlLLLites as Checkpoints, and since 0.44.10 a download of one was moved into Stable-diffusion, where Forge offers it as a checkpoint and its ControlNet does not list it. They are told by the names Forge's ControlNet loaders look for (checked on 19 published files), filed under ControlNet, and the Type filter has a ControlNet entry. And a file is moved as a Checkpoint only when Forge's own detector recognises it. If you have ControlNets, run Scan Disk once with "Re-evaluate file headers".
- **0.44.22** (build 328) - The Generations tab's settings gear opens the settings window on that tab's sections again: since 0.44.21 it named a tab called "TAB". Every tab's gear and version, and both tabs' downloads panel, are now drawn from one place instead of a copy each.
- **0.44.21** (build 325) - Copy JSON in an image's metadata window copies again: since 0.44.18 the window stopped the click before it reached the listener that copies. Buttons, cards and switches in the shared parts of both tabs, and in the tabs' own markup, now name what they do (`data-action`) and one listener for the page runs it - they called window globals from strings of JavaScript that no check could follow.
- **0.44.20** (build 323) - A thumbnail of your own images is badged as a Civitai image's card is: R, X and XXX from their rating, as well as "X · prompt" where the prompt raised it - it showed only the last. A model's Your generations and the Generations tab also draw that thumbnail, and ask to rate and to delete, through one piece of code instead of a copy each.
- **0.44.19** (build 321) - The Model Manager's and the Civitai Browser's image galleries page one way: Load More, adding a page without drawing the others again, and saying why a page did not come are one piece of code for both, where each tab had its own. One difference showed: after a page failed to load, Load More in the Model Manager kept the old error up while it tried again; now, as in the Civitai Browser, it clears it, and says so again if the page still does not come.
- **0.44.18** (build 320) - A Civitai image reads the same in the Model Manager and the Civitai Browser. Their cards were two copies that had drifted: the browser read a sampler and scheduler from six fixed scheduler names - "Euler a Uniform" showed as one sampler - where the Model Manager uses Forge's own list, and only the Model Manager listed ADetailer's "inpaint only masked". Both tabs now draw one card. Show All opens one window in both: the table of every field, with a Copy JSON button for the image's generation data.
- **0.44.17** (build 317) - Moving between tabs no longer depends on a tab's label, its place in the tab bar, or a fixed wait. Show in Model Manager, Show in Civitai Browser and the Generations tab's links found a tab by its English name, and Send to img2img took the second tab for img2img: with a translated or reordered tab bar they went nowhere, or to the wrong tab. They find each tab by its id now. They also searched 100 ms after clicking the tab, while a slow page could still be drawing it; now they wait until it shows. And from the Generations tab, a Civitai Browser that has not loaded is reported there, not in the Model Manager's status line.
- **0.44.16** (build 311) - The rest of the WebUI no longer waits while the Model Manager reads its database or the disk. Eighteen of its requests - the grid, a model's details, Delete, pins and bookmarks, the Generations tab's pages, the sync estimate, the settings window, the download controls - ran on the WebUI's one event loop, so everything else waited on them; a pin clicked while a sync was writing could hold it for up to 30 seconds. They run beside it now.
- **0.44.15** (build 309) - In the Civitai Browser, a model you hold only through a version Civitai has since deleted was "Owned" on its card but not in its details, which then left out "Show in Model Manager". Both now go by one rule: the model is yours if any file in your library is of it.
- **0.44.14** (build 308) - The Model Manager grid counts its cards and reads its page from one snapshot of the library. Read apart, a sync, a scan or a download finishing in between could leave the total and the page disagreeing: a card missing or shown twice across pages, or one more page offered than there is.
- **0.44.13** (build 296) - Deleting a model also deletes its .cm-info.json, the side file another tool may have left beside it, which was left behind; the files deleted with a model are now the same ones Scan Disk moves with it.
- **0.44.12** (build 288) - The Generations tab has a setting of its own for whether it opens with explicit images hidden: "Generations tab: hide explicit images by default", in the settings window's Your generations and on the Settings page. It used to follow the Model Manager's image gallery setting; it starts from what that says, so nothing changes until you change it. A model's Your generations, in the Model Manager, still follows the image gallery's.
- **0.44.11** (build 286) - The Scan Disk dialog is wider - half the window, up to 800 px - so its list of files to move into their type's folder reads without wrapping every path.
- **0.44.10** (build 280) - A download goes in the folder for what the file is, not what Civitai calls it. A VAE or a text encoder shared as a "Checkpoint" landed in Stable-diffusion, where Forge offered it as a checkpoint and not in the VAE / Text Encoder box - 22 of 1,160 files in one library would have been misfiled. Once a file arrives its header is read, and it goes to its type's folder, keeping its subfolders; the download says where it went. Nothing is written over: the same file already there is kept and the new copy removed, and a different file of that name leaves the download where it landed. For files already in another type's folder, Scan Disk has a new box, "Move files into their type's folder", which lists them - what each is, where it would go, and which will stay because their name is taken - and moves them only when ticked, with their .civitai.info and preview, their place in the library, their pin and their generations.
- **0.44.9** (build 279) - Esc closes one thing, the one in front. It closed the first metadata or Resources window on the page whichever tab had opened it, and the Civitai Browser's open model with any Esc - closing the viewer, a question, or a dialog in another tab closed it too. Each window now closes itself; the Civitai Browser closes its tag suggestions, then its open model, only while it is the tab showing and nothing is open over it.
- **0.44.8** (build 278) - One model file is one entry in the library, however its path is spelt. Windows ignores the case of a path and the database did not, so a scan or sync that found a file under a differently-cased path - two WebUIs sharing the database with their folder options typed differently, say - would have added it a second time. A path the library already holds in another case is now the same file, under the spelling it was first stored with. No file in a library of about 1,500 was affected; this keeps it so. The database gains an index (v30) and nothing else: a second WebUI sharing it can be updated later.
- **0.44.7** (build 277) - A model whose .civitai.info went missing no longer shows "No Civitai Data". Scan Disk, finding no file beside it, marked it unknown to Civitai though the library still held everything about it, and the Has Civitai Data filter and the sync's counts followed. It stays identified now; the next sync, seeing the .civitai.info gone, syncs the file again and writes it back, as it used to.
- **0.44.6** (build 276) - After an update, the browser loads the new version of the scripts the three tabs share. They were asked for with each tab's own version, which stays the same when only a shared script changed - as in 15 of the 60 updates that changed one - and the WebUI does not tell browsers to check again, so a browser could keep running the old one until it was hard-reloaded. They now have a version of their own, and the three tabs load each of them once instead of once per tab.
- **0.44.5** (build 273) - A sync no longer makes a model a Checkpoint when Civitai's answer leaves out its type. It filled in "Checkpoint", which was stored over the type the library already knew - a LoRA among them - and shown wherever Civitai's type is; a model Civitai gives no type is now Unknown, as Scan Disk already stored it, and a type already known is kept.
- **0.44.4** (build 272) - A sync or a scan that fails says so. One that stopped on an error kept showing as running, for ever: the error was kept where the page never looked. It now finishes, with the error - a sync shows its message, a scan its count, the message in the console - and what it had done before it stopped.
- **0.44.3** (build 271) - The extension runs as one copy. At startup it used to load itself a second time for its endpoints, while the recording of your generations and the settings kept the first: turning "Check for updates" on checked in the copy the page never reads, so nothing showed for up to 12 hours, and each copy opened the database and kept a downloads list of its own - a download running through Settings -> Reload UI was lost to the new list. Reload UI no longer picks up edited Python; Extensions -> Apply and restart UI, a real restart, does.
- **0.44.2** (build 270) - Everything that asks Civitai keeps to the rate you set, together. Each sync, download, search and gallery page made its own client with its own budget, full, so a sync running while you browsed went past it; they now draw from one, and browsing during a sync waits its turn. The log no longer prints two lines each time. An API key pasted with a space or a newline around it is trimmed for downloads too - the API trimmed it, the download header sent it as pasted - and a key of spaces alone counts as none.
- **0.44.1** (build 269) - The library looks in every folder a download files into. Upscalers, ControlNets, hypernetworks, motion modules, poses, wildcards and Other were downloaded into folders Scan Disk never walked, so the next full scan or sync forgot each one as a file gone from disk; they are walked now, and the models already in them join the library at the next scan. A scan or sync forgets a file only once it is really not on disk - a wildcard pack's .zip, or a file your folder template put elsewhere, keeps its place. An upscaler download honours --esrgan-models-path, and a ControlNet Forge Neo's --controlnet-dirs.
- **0.44.0** (build 268) - Scan Disk no longer lowers a version's NSFW level to PG. A file whose `.civitai.info` was missing or unreadable, or listed no versions, was stored as PG over the level a sync had written, so an X model showed under a PG filter. A scan with nothing to say about the level now keeps the stored one; a file the library has never seen, with nothing beside it, is still PG, so it shows under any level filter.

## 0.43 - Downloads you control

*1 October 2026*

Downloads can be paused and resumed - carrying on from where they stopped, after a restart or a crash too - and the queue can be steered: a waiting download started now, moved up or down, or cancelled before it starts, and everything paused or resumed at once. The list keeps one order, which only you change.

- **0.43.5** (build 267) - Videos start sooner in the viewer: it plays a Civitai copy as wide as it shows it - never wider than the video - where it played the original upload, which often keeps its index at the end of the file, so the browser fetched the end before a frame; a copy has it at the start, and was 45-93% of the original's size. And a video card no longer downloads a whole video for its preview: Civitai now and then serves the original (32 MB for one) where the still should be, so the still is checked to be an image first, and the browser remembers the answer.
- **0.43.4** (build 266) - A paid version you have bought on Civitai downloads like any other, with your API key. Civitai's version details never say who bought what, so its permissions check is asked - once for every paid version shown, remembered a few minutes. One you have not bought keeps its Paid label, saying why; a purchase takes Civitai's API some minutes to see, so it says that too. If Civitai refuses a download anyway, its own reason is shown, with a link to the version's page.
- **0.43.3** (build 265) - The Generations tab's ⋯ menu names models by version, not by file path: "Show model in Model Manager" opens the checkpoint's version, a new "Show model in Civitai Browser" opens its model there, and each LoRA the images used has a "Show LoRA ... in Model Manager" of its own. A model the library no longer has is greyed, saying so, instead of a search that finds nothing; a file Civitai does not know is still found by its file.
- **0.43.2** (build 263) - "Show model in Model Manager", from a generation or the Civitai Browser, found nothing for a model with an explicit image while "Only Show Models with SFW images" was ticked - every other filter was loosened for the jump, not that one. It is now, and a model that really is not there is named by its file, not by "path:" and its full path.
- **0.43.1** (build 262) - A File Size filter in the Model Manager's Advanced filters: a range in GB, either end open. A model shows if any of its local files is in range, with the newest that is; it is kept with Save Search. The library knows every file's size, so unlike the Civitai Browser's it is exact and paged like any filter.
- **0.43.0** (build 261) - Pause, resume and order downloads. A running download can be paused: it keeps what has arrived and lets the next in the queue start; Resume asks Civitai for the rest only, its hash carried on, and checks the finished file as before. Paused downloads, and one running when the WebUI stopped, are there after a restart, to resume. A waiting download can be started now (beside the two running), moved up or down, or cancelled; Pause all and Resume all are in the panel's header. Rows keep their place whatever their state; the first waiting from the top starts when a place frees up. Civitai's storage now and then sends the whole file for a resume, so it is asked again, up to three times, before starting over.

## 0.42 - Grouping in two levels

*30 September 2026*

The Generations tab groups by two things at once - a model, then the prompts used with it; a day, then the models - from a Group by menu that opens each grouping's "then by" list beside it. The first grouping is a header row across the grid, the second its groups under it, and a group opens straight onto its batches.

- **0.42.3** (build 260) - The downloads panel says how fast a download is going and how long it has left: "42.1% - 2.70 GB / 6.50 GB · 12.4 MB/s · about 5 min left". The speed is the last 5 seconds', so it does not jump with each chunk; nothing arriving for 5 seconds reads "stalled", not 0 B/s.
- **0.42.2** (build 259) - A model card's cover no longer changes between loads when two of its versions share a publish date - Deep Negative's V1 75T and V1 64T to the millisecond, or two with none. The card showed whichever the database returned; the tie now goes as Civitai orders versions, the one its own page shows, then by version, so it is always the same. 2 of 1,005 cards in one library change, to what Civitai shows.
- **0.42.1** (build 258) - Group generations by base model - Illustrious, Pony, SDXL 1.0, Flux.1 D ... - alone or with another grouping ("Base model › Model"). It is the checkpoint's base model as the library holds it, the one the Model Manager's Base Model filter reads; a checkpoint the library has none for is Unknown.
- **0.42.0** (build 257) - Group by two things in the Generations tab. Group by is a menu: a click on a grouping groups by it; its "then by" list, on hover, adds a second, any of the other five. Grouped twice, the grid is in sections - a header row per group of the first, with how many groups and images it holds, and the second's groups under it - and a group opens onto its batches, Back one level at a time; Select is hidden among groups. Also: four of the extension's after-update callbacks rewrote their text every time - the Group by button, the new-version notice and both SFW banners - and each rewrite made the WebUI run every callback again, four times a second, without end. They now write only what changed.

## 0.41 - Notes to you, per release

*30 September 2026*

The tabs now say what is new, and what to do after an update: a note at the top of the tab it concerns - a feature worth knowing, something to do once (with a button that does it), or a warning - dismissed with one click, for every browser using the database. A fresh install sees only what is for everyone; an update also sees what it needs to do. The settings window's new "What's new" keeps every note, dismissed or not.

- **0.41.14** (build 256) - A LoRA an image names twice - by Civitai's version and by its file's name - is one chip, not two. Hashes an image keeps as "LORA:name" or "EMBED:name", in capitals, were missed (5,561 and 35 in one library), so the LoRA lost its hash and came out as a second chip with "no hash recorded". Those are now read, and a chip with no hash anywhere is merged into the chip whose file has the same name - the file installed, or the one Civitai names for its version - keeping the weight only the image's own list gave.
- **0.41.13** (build 255) - A gallery's switch numbers no longer jump when a switch is flipped. An image hidden by both the NSFW filter and the prompt filter was counted as NSFW, so "Show NSFW" said 51 and, once ticked, 49 - the other 2 still hidden for their prompts. Such images are now counted apart ("2 hidden due to both"), "Show NSFW" says what it alone would show, and "Show unusable prompts" every image with an unusable prompt, however either switch is set. In the Model Manager's gallery, the Civitai Browser's and your generations.
- **0.41.12** (build 254) - The "new version available" notice gives the build too - "v0.41.12.254 available" - as the version beside it does.
- **0.41.11** (build 253) - Says when a newer version is out: "v0.42.0 available" beside the version in each tab's header, linking to the changelog, its tooltip saying how to update. The extension reads `version.json` from its GitHub repository, on the branch it was installed from - the version it holds, nothing it runs - after the WebUI starts and every 12 hours. "Check for a new version" in the settings turns it off, and then GitHub is never asked.
- **0.41.10** (build 252) - A note's Dismiss stays in one place as you work through the pile: the ‹ 1 of 3 › beside it is as wide as the count needs, its digits all one width, and the last note keeps it as "1 of 1" - where Dismiss moved with the count, and jumped right when the last-but-one note went.
- **0.41.9** (build 251) - Select, to delete many generations at once: in the Generations tab and a model's Your generations, a tick on every batch, image and card - a click anywhere on the image ticks it, shift-click ticks a range, Select all loaded ticks every one - and one Delete for them all, asked once, saying how many images of how many generations and how many of them the NSFW filter hides, with the files as a choice. Hidden where there is nothing to tick (grouped, at the top). The Generations tab's Group by row and banner now stay at the top while the grid scrolls, as the other tabs' do.
- **0.41.8** (build 250) - A gallery says it is loading, in both tabs: opening a model or a version clears it at once to a bar and "Loading images...", and changing a switch dims the images under the bar, their switches off, until the new ones are in - where nothing showed for seconds. A first page that fails is said in the gallery.
- **0.41.7** (build 249) - Save a search in the Civitai Browser: Save Search keeps the filters - query, type, base model, sort, NSFW, tag, size and the rest - and the tab opens with them, searching the first time it is shown; right-click clears it. The Model Manager's Save Search is kept in the database too, no longer in the browser, and one saved there before is moved over: the same in every browser, and in both WebUIs sharing the database.
- **0.41.6** (build 248) - The Model Manager's and the Civitai Browser's introductions are shown to everyone updating as well as to a first install, once, until dismissed.
- **0.41.5** (build 247) - A first install's introductions, in the Model Manager and the Civitai Browser, are headed [Important], as the Generations tab's note is.
- **0.41.4** (build 246) - A first install is shown around: the Model Manager's note says how to get your models in - Scan Disk, then Sync with Civitai's Force sync on the files Civitai has not identified - with a button that opens each dialog, Sync already set; the Civitai Browser's what it is for, and where the API key goes. Only for installs new since this version; notes can now carry several buttons.
- **0.41.3** (build 245) - Messages point at the settings window, not the WebUI's Settings page: the "No Civitai API key" banners and the Civitai Browser's SFW banner have a link that opens it at the setting; the NSFW note, Send's notice about a missing text encoder or VAE, and a download refused for want of a key say where it is. Ticking "Only Show Models with SFW images" shows its banner again, in both tabs: the box's listener was lost when the tab was drawn late or redrawn.
- **0.41.2** (build 244) - The settings window opens with every section collapsed but the ones the tab it was opened from uses: the Model Manager's its connection, grid, gallery, generations, NSFW and storage sections, the Civitai Browser's its own, the Generations tab's Your generations and NSFW detection. A note's Open settings button opens only the section it is about, and scrolls to it.
- **0.41.1** (build 243) - One switch for your generations: "Your generations" in the settings, where "Record the images you generate" was. Off, nothing is recorded, and the Generations tab and each model's Your generations are hidden at once; from the next start the Generations tab is not created at all. What was recorded is kept, and comes back when it is on again. The Generations tab's note says so.
- **0.41.0** (build 242) - Notes to you, per release, at the top of each tab: a pile, one note in full and the edges of the rest under it, stepped through with its arrows or spread into rows; [Important] ones first, then what to do, warnings and features. A later note can replace an earlier one that asked the same. All of them stay under "What's new" in the settings window. The first ones: run Scan Disk once with "Re-evaluate file headers"; update the extension in your other WebUI when the two share a database (shown only when a database file is set); the Generations tab, grouping it, rating your own images, pinning, and the image viewer. The Generations tab's tiles are 4px apart.

## 0.40 - Generations

*29 September 2026*

A Generations tab, before the Model Manager, holds every image you have generated, newest first, whatever model made it: a tile per generation - a batch its first four images and how many it has, opening out in place - that loads on as you scroll, with the NSFW filter. A click opens an image in a viewer, as large as the window, stepping through them all with the arrow keys or the wheel, the prompt and every setting beside it. Sending one back now sets Forge up as it was made - its preset, checkpoint and exactly its text encoders and VAE - which the infotext alone never did, as Forge Neo ignores those lines by default.

- **0.40.13** (build 241) - The Model Manager's grid has two tabs, 📌 Pinned and Unpinned, in place of pinned models coming first: the search and filters apply to both, and each says how many match them. The page opens on Unpinned; a tab only changes what a loaded grid shows, and loads nothing before Load Models. The tabs and the status line line up with the grid's cards, and "Show model in Model Manager" finds a pinned model in its tab.
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
