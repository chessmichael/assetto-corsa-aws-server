# Joining the Server — a Guide for Players

You've been invited to a private Assetto Corsa server hosted by a friend. This is
everything you need to get on track. No AWS, no command line — about 5 minutes.

## What you need

1. **Assetto Corsa** (the game, on Steam).
2. **Content Manager** — the community launcher everyone uses. If you don't have
   it yet, grab it from [acstuff.club/app](https://acstuff.club/app/) and run it
   (point it at your AC install when it asks).
3. **The content pack** your host sent you (a folder or `.zip` of the exact
   car(s) and track for this server).
4. **The server address and password** — your host gives you both. For example:
   - Address: **`<server-address>`**  (looks like `203.0.113.10:8081`)
   - Password: **`<password>`**

> ⚠️ You must install the **exact** content the host sends. If your copy of a car
> or track differs even slightly, the server will reject you with a "checksum"
> error. Don't substitute a different version from elsewhere.

## Step 1 — Install the content pack

The host sends you a folder (made with `ac share`) that contains `content\cars\…`
and `content\tracks\…`. Install it one of two ways:

- **Easiest:** drag the `.zip` onto the Content Manager window — it detects and
  installs cars/tracks automatically.
- **Manual:** copy the `cars` and `tracks` folders into
  `…\Steam\steamapps\common\assettocorsa\content\` (merge with what's there).

## Step 2 — Connect to the server

Because this server is small and private, the most reliable way in is a **direct
connect link**. Press **Windows + R**, paste this, and hit Enter:

```
acmanager://race/online/join?ip=<server-ip>&httpPort=8081
```

Content Manager opens straight to the server. (You can also paste that line into
a browser address bar and allow it to open Content Manager.)

**Alternative:** in Content Manager → **Online**, search the server name
("Boston …"). It shows with a 🔒 because it's password-protected. Don't hammer the
refresh button — the public list rate-limits rapid reloads.

## Step 3 — Drive

1. Select the server → click **Join**.
2. Enter the **password** your host gave you when asked.
3. Pick a car and a skin → **Join / Drive**. You're on track. 🏁

## If something goes wrong

| Problem | Fix |
|---|---|
| **"Checksum failed" / kicked on join** | Your car/track doesn't match the server. Re-install the exact pack the host sent; remove any other version of that mod. |
| **Can't connect / times out** | Double-check the address and password your host gave you. Make sure the host has the server **on** (ask them to run `ac start`). |
| **Can't find it in the Online list** | Use the direct-connect link in Step 2 — it bypasses the public list entirely. |
| **"Can't connect to the internet for servers"** | The public lobby rate-limited you for refreshing too fast. Wait a few minutes, or just use the direct-connect link. |

That's it — see you on track.
