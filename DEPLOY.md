# Putting Nearest Kickoff online

Domain: **nearestkickoff.com**, registered at Porkbun.
Contact address: **contact@nearestkickoff.com**.

Porkbun is your registrar — it owns the name and the DNS. The site itself is better hosted
elsewhere and pointed at from Porkbun. That is the normal setup, and Porkbun is built for it.

Budget about an hour. Everything below is free.

---

## Step 1 — Turn on the email address (5 minutes)

Porkbun includes **up to 20 free email forwards per domain**, which is all you need: mail sent
to `contact@nearestkickoff.com` lands in the inbox you already read.

1. Log in to Porkbun, go to **Domain Management**.
2. Find `nearestkickoff.com` and click **Details**.
3. Open **Email Forwarding**.
4. Forward `contact` → your everyday inbox.
5. Send yourself a test from another account and confirm it arrives.

**Forwarding receives but does not send.** If you later want to *reply* from the address — worth
having for the affiliate application — Porkbun sells a real mailbox at about $36/year. Receiving
is enough to launch.

---

## Step 2 — Fill in the last two blanks

Everything else is already filled in. Two remain, both genuinely yours to decide:

| File | What is left |
|---|---|
| `privacy.html` | `[your name or company]` — who is legally responsible |
| `terms.html` | `[your name or company]` and `[country]` — whose law governs the terms |

Your own name is the right answer for the first if there is no company. For `[country]`, pick
where you actually live; it decides where a dispute would be heard, so if you are unsure, ask
someone qualified rather than guessing.

Open the files in any text editor, use Find & Replace, save, and **delete the yellow boxes**.

---

## Step 3 — Host the site

Use **Cloudflare Pages** or **Netlify**. Both are free, both give you HTTPS automatically, and
crucially **both read the `_headers` file in the folder** — that file applies the security and
caching rules, so don't delete it even though it looks like a stray.

Porkbun does offer its own static hosting, but it is a registrar first and the `_headers` support
is not something to rely on. Keep the domain there and host the site properly.

### Cloudflare Pages

1. Sign up at **dash.cloudflare.com**.
2. **Workers & Pages → Create → Pages → Upload assets**.
3. Name the project, then **drag the unzipped `nearestkickoff-site` folder** onto the page.
   Drag the *folder*, not the zip.
4. **Deploy site.** You get a live `.pages.dev` address in about a minute — check it works
   before touching DNS.
5. **Custom domains → Set up a custom domain →** `nearestkickoff.com`. Cloudflare shows you the
   DNS record to create.

### Netlify

1. **app.netlify.com/drop**, drag the folder on. It is live immediately.
2. Make a free account to keep it.
3. **Domain settings → Add a custom domain →** `nearestkickoff.com`, and it shows you the record.

---

## Step 4 — Point Porkbun at the host

In Porkbun: **Domain Management → nearestkickoff.com → Details → DNS**.

Porkbun has a **Quick DNS Config** for common hosts — check whether yours is listed, because it
fills everything in for you. Otherwise add the record your host showed you in step 3:

- For the bare domain `nearestkickoff.com`, Porkbun supports **ALIAS** records, which is what you
  want. A plain CNAME is not allowed on a bare domain; ALIAS does the same job legally.
- For `www`, add a **CNAME** pointing at the same host target.

Then set `www` to redirect to the bare domain (or the reverse) so you only have one address, not
two competing ones. Both hosts do this in their domain settings.

**DNS changes take minutes to a few hours.** If the site does not appear immediately, wait before
changing anything — most "it is broken" moments at this stage are just propagation.

---

## Step 5 — Check it properly

- the map loads and pins appear
- typing a town into **"where are you"** gives suggestions
- **Credits & licences**, **Privacy** and **Terms** open from the bottom left
- no `[your name or company]` or `[country]` text remains anywhere
- the yellow boxes are gone
- the **i** at the bottom right of the map lists the data sources
- `https://` works and the browser shows no warning
- **open it on your phone** — that is the view most people will use

---

## Step 6 — Apply to Sports Events 365

Only once the above is done. The direct programme at `aff.sportsevents365.com` is free to join
and has no minimum traffic requirement. Do not apply with placeholder text still on the pages;
a reviewer clicking through to `[your name or company]` is the easiest rejection there is.

---

## Updating the site

Fixtures move constantly. The rebuild is three commands on a computer with Python:

    python3 ingest/calendars.py <every calendar file>
    python3 ingest/build.py
    python3 ingest/verify.py

Then drag the folder onto your host again — it replaces what is there, and both hosts keep the
old version so you can roll back if something looks wrong.

---

## Before any ticket link goes live

Section 166 of the Criminal Justice and Public Order Act 1994 makes it an offence for an
unauthorised person to sell, or offer or expose for sale, a ticket for a designated football
match — which covers virtually all professional football in England and Wales — and the Violent
Crime Reduction Act 2006 extended it to sales over the internet. An affiliate ticket link is
arguably an offer for sale made in the course of a business. **Get a legal opinion before any
ticket link points at an English or Welsh fixture.** Scotland is outside s.166, as is everywhere
else on the map.

When links do go live, `disclosure.html` already holds the affiliate text, commented out and
ready. Publish it and update `privacy.html` the same day — affiliate links set third-party
cookies, and the privacy policy currently says truthfully that the site sets none.
