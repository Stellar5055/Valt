# Valt


## What it is

Valt is a vault, you pick folders to put in different compartments and give a different password to each compartment and pack everything into a .valt file.

You can unlock that file with different passwords to open different containers. It uses AES-256-GCM and inteligent techniques, so there is no realistic way to break into it or even see the other containers without the password as long as the passwords are strong, since bruteforcing works on weak ones.


## Demo


https://github.com/user-attachments/assets/c1ff5696-6c1a-43d1-9905-a031054592a8


This is a short demo video showing a demo of the gui version


## Install

Scoop is recomended, install using scoop with:
```
scoop install https://raw.githubusercontent.com/Stellar5055/Valt/main/bucket/valt.json
```
You can update the app with:
```
scoop update valt
```

Or if you dont want to use scoop, you can install with:
```
irm https://raw.githubusercontent.com/Stellar5055/Valt/main/install.ps1 | iex
```
Run this command again to update.

Or you can download the exe directly from the [latest release](https://github.com/Stellar5055/Valt/releases/tag/latest)

All these gives you 2 apps - valt.exe and valt-cli.exe. valt.exe is the main app (~15MB) which is gui, and user friendly, and valt-cli.exe (~11MB) is for devs or more experienced people and in this, you can run commands to perfom these actions - just run **`valt-cli --help`** after installing to test


## How to use

**For the GUI app:**

Open the app, go to the create tab, add compartments with unique passwords that are atleast 8 characters, chose one folder for each compartment and then click on create vault to pack it. This opens a file explorer window where you select the location to store the .valt file. Thats it, your .valt file is created and ready to use!

To unlock it, you can either double click a .valt file to open the app with this vault selected or select it from the app, then enter a password and the list shows all compartments and files in them with that password. add or remove compartments, select one or more compartments to edit or change the password or extract them. extracting them asks you for an extract dir and after you select that, it extracts the contenst of the selected compartments there.

**For valt-cli:** 

It does everything the GUI does:
```
valt-cli create my.valt --folder C:\Users\me\secret
valt-cli open my.valt
valt-cli extract my.valt OUT --compartment secret

Passwords are always typed in hidden prompts, never as command line arguments, so they never end up in your shell history.
```

## How it Works

Each folder gets a random key, is encrypted with it (AES-256-GCM), and is appended to the vault file. That key plus the folder's label and position is sealed with your password (Argon2id, slow on purpose to slow down bruteforcing). Unused slots are filled with random junk, so a full slot and an empty one look almost same - one password opens only its own folder, and reveals nothing about the others.

A wrong password isn't detected, it just decrypts to garbage, and the built-in integrity check proves it's garbage. Extract decrypts with the folder key (which never leaves your machine), change password only re-locks the small payload which is instant - and remove wipes the slot with random junk,
leaving the data behind as bytes no key can open.


## Notes

Forgotten passwords can never be recovered, there is no way to hack it, brute forcing is extremely slow.

Built for only windows.

Made almost by me, but towards end, used ai to vibecode the gui and some small features and bug fixes, but all the foundations and internals are made by me

Please refer to my [Journal](JOURNAL.md) - I put a lot of effort into it, and i have also exported my agent sessions to be open about teh ai uses, there are 2 versions - [Readable - no toughts and tool calls](session-readable.md) and [Full session for reference](session-full.json)
