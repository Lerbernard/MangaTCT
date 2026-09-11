# Accounts, coins and billing

The editor runs on the customer's own machine. Everything it can reach, they
can reach — with a browser console and their own ID token they can send
whatever request the rules permit. So the whole design is one sentence:

**Nothing a client holds may write a balance.**

Coins move in Cloud Functions and nowhere else. The Admin SDK bypasses the
security rules, which is exactly why the rules can be as strict as they are.

## What is here

| file | what it is |
|---|---|
| `firestore.rules` | what a signed-in person may read and write. The security core. |
| `functions/purse.js` | every decision about money and usernames, as pure functions with no Firebase in them. |
| `functions/index.js` | the Firestore and Stripe wiring around `purse.js`. Talking, no deciding. |
| `functions/package.json` | the functions' dependencies. |
| `functions/seed.js` | writes `config/prices` and `config/stripe` once. Not deployed. |

`firebase.json` and `.firebaserc` are **in the repository root**, not in here.
Firebase Hosting refuses to serve a folder outside the directory holding
`firebase.json`, and the site is `../site` from here — so the project root is
the repository root, and every `firebase` command is run from there.

And outside this folder, the two halves that use it:

| | |
|---|---|
| `../site/` | `signin.html`, `pricing.html`, `account.html`, and `config.js` — **the one file you fill in.** |
| `../account.py` | the editor's client: sign in, and spend against the account. |

`purse.js` is pure on purpose. The rules and the transactions can only be
tested against the emulator, and the emulator is a 60MB download from Google's
storage. The part that decides how much money moves does not need any of that,
and it is the part that must not be wrong.

## Testing

```
npm run test:money    # the money and username decisions — runs anywhere
npm run test:rules    # the security rules, against the Firestore emulator
npm run test:js       # both
```

`test:money` runs in this repo today: 63 tests, no network, no emulator, and
every one of them survives a mutation pass over `purse.js`.

The editor's side has its own suite, in Python, which fakes the wire rather
than reaching Google:

```
python -m pytest tests/test_the_account_the_coins_live_in.py
python tools/mutate.py -k acct       # and the mutation pass over it
```

`test:rules` needs the Firestore emulator, which downloads a JAR from
`storage.googleapis.com` on first use. That download is not reachable from
every environment; on a normal machine it just works. **The rules have not been
executed in the sandbox they were written in** — the file is complete and the
tests are real, but run `npm run test:rules` on your machine before trusting
them.

## The data

```
users/{uid}
  username         the display form — what they typed
  usernameKey      what uniqueness was checked against (folded, lowercased)
  displayName      shown on the account page
  photo            a preset id or a URL
  coins            THE BALANCE. Functions only.
  stripeCustomer   Functions only
  granted          {sessionId: true} — so a retried webhook is not free coins
                   {welcome: true}   — the hundred free coins, given once
  clawed           {chargeId: coins} — what a refund has already taken back
  users/{uid}/ledger/{id}   the receipt. Functions write, the person reads.

usernames/{key}    the uniqueness index. The document ID IS the folded name.
  uid

welcomed/{sha256 of the email}   which addresses have had their free coins,
  uid, at          so delete-and-recreate gets nothing twice. Functions only.

config/prices      the tiers and packs, for a page that has not signed in yet
```

### The hundred free coins

A new account is given `WELCOME` (100) coins **once its email is verified**.
The grant happens inside `me`, the first call every signed-in page and the
editor make: `welcomeIfDue` reads `email_verified` off the signed ID token —
never off the request — and moves the coins in one transaction that also
writes `granted.welcome` on the user and creates `welcomed/<hash>`. A Google
sign-in arrives verified and is welcomed on its first `me`; a password
sign-up gets the verification mail (sent by the site's sign-up form and by
the editor's) and is welcomed on the first `me` after the link is clicked and
the token has been refreshed. There is no `claimWelcome` callable on purpose.

### Why usernames are a separate collection

"Is it taken?" is a document read and "take it" is a create that fails if the
document exists. That is what makes it atomic: two people claiming the same
name at the same moment are two creates of one ID, and exactly one of them
loses. Checking a field on a user document and then writing it is a race with a
window, and the window is exactly as long as a round trip.

The ID is the *folded* name, so `Lee`, `lee`, `l3e`, `l.e.e` and `ｌｅｅ` are one
name. Uniqueness that is only byte-uniqueness is an impersonation problem on
day one.

## What you have to do

None of this can be done for you — it is all accounts in your name. In order,
and nothing here needs a line of code changed.

**1. The Firebase project.** `firebase login`, then create the project in the
Firebase console.

It asks for a **project ID**, which is Google's own name for it — it turns up
in `<id>.firebaseapp.com` and in the URL of every function, and it cannot be
changed afterwards. Something like `mangatct`; if that is taken, `mangatct-app`
will do. It is **not** the name of any file in this folder.

*Then* open `.firebaserc` — in the repository root, beside `firebase.json` —
and put the id you chose inside it, so the CLI knows which project a
`firebase deploy` means:

```json
{
  "projects": {
    "default": "mangatctproject"
  }
}
```

That is the real one. The project's *display name* is MangaTCT, but the ID
Google issued is `mangatctproject`, and the ID is what every command means —
it is also what `<id>.web.app` and every function URL are built from.

**2. Blaze plan.** Cloud Functions need pay-as-you-go billing enabled. The free
allowance is generous; this is about the plan, not the bill.

**3. Sign-in methods.** In Authentication, enable **Email/Password**, and
**Google** if you want the button on the sign-in page to do anything.

**4. Fill in `../site/config.js`.** Firebase Console → Project settings → your
web app → the config object. Copy it in. Those values are not secret — a web
API key says *which project*, and the rules say what may be done — which is why
this one file is read by the website *and* by the editor, so there is only ever
one place to get it right.

**4b. Create the Firestore database.** Build → Firestore Database → Create
database. **Production mode** — the rules in this folder replace the default
ones on the first deploy, and starting in test mode means a window where
anybody can read anything.

Pick the location carefully: it is the one other thing that cannot be changed
afterwards. `nam5 (us-central)` sits beside where the functions deploy by
default, which is what you want — a database in one continent and the functions
in another is a round trip added to every call.

There is nothing to put in it. `onNewUser` makes each account's document, and
step 7 writes the price list.

**4c. Install the functions' dependencies.**

```
cd firebase/functions
npm install
```

**5. The Stripe secrets.** Never in a file, never in the repository:

```
firebase functions:secrets:set STRIPE_KEY              # sk_live_... or sk_test_...
firebase functions:secrets:set STRIPE_WEBHOOK_SECRET   # whsec_... (step 8)
firebase functions:config:set                          # nothing else needed
```

**5b. The provider keys the relay calls with.** lee: *"the user shoud not
have eth keys"*. The editor's AI steps go through the `relay` function
(`functions/relay.js`), which calls Claude, Gemini and OpenRouter with these
and is paid in coins; the person never holds a key. Same mechanism, never in
a file:

```
firebase functions:secrets:set ANTHROPIC_KEY     # sk-ant-...
firebase functions:secrets:set GEMINI_KEY        # AIza...
firebase functions:secrets:set OPENROUTER_KEY    # sk-or-...
firebase functions:secrets:set CLEAN_TOKEN       # CLEAN_TOKEN out of the cleaner's deploy file
firebase functions:secrets:set CLEAN_URL         # the https://...modal.run address that deploy printed
```

Paste each when prompted (the prompt shows nothing, so paste ONCE). A key you
leave unset makes that provider answer 503 "not set on the server"; the
others still work. The cleaner is the fourth key lee named (*"ther 4 key one
for teh clner do tha too"*): its token travels in the request body, not a
header, so the relay rewrites that one field, and its reply is a PNG. The relay checks the caller's ID token and that the
account has coins, forwards the request unchanged, and logs the provider's
usage; the price is held and settled by the editor as before (`spendCoins`).

The site URL Stripe returns people to defaults to `https://mangatct.com`. To
change it: `firebase deploy --only functions` after setting the `SITE_URL`
parameter, or answer the prompt the CLI gives you on first deploy.

**6. The Stripe products.** Four one-off prices, one per pack. Nothing
recurring — there is no subscription.

Each product needs a **product tax code**, and it has to be one the dashboard
marks *Eligible for Managed Payments* — for this, the SaaS / digital-services
codes. A product without an eligible code cannot be sold through Managed
Payments at all, and it fails at checkout rather than at setup.

Payment methods are a switch in the Stripe dashboard, not code here — which is
the whole reason this is Checkout and not a card form. lee: *"for payment allow
many difrent ways to pay"*.

**7. Tell the database about them.**

```
cd firebase/functions
node seed.js price_pack1=price_1A... price_pack2=price_1B... \
             price_pack3=price_1C... price_pack4=price_1D...
```

That writes the public price list *and* the id map. Run it again whenever a
price changes; it merges.

**8. Deploy, then set the webhook.** From the repository root, not from this
folder:

```
cd ..
firebase deploy --only firestore:rules,functions,hosting
```

Hosting goes to `https://mangatctproject.web.app` first. Point `mangatct.com`
at it afterwards, in Hosting → Add custom domain, and change `SITE_URL` to
match — until then Stripe would send a paying customer back to a domain that
does not resolve.

Take the printed `stripeWebhook` URL into the Stripe dashboard → Developers →
Webhooks, subscribe it to `checkout.session.completed` and `charge.refunded`, and put
the signing secret it gives you into `STRIPE_WEBHOOK_SECRET` (step 5). Then
deploy the functions once more so they can see it.

A webhook nobody verifies is an endpoint that grants coins to anyone who posts
to it, so the signature check is the first thing that function does — before
the body is read as anything but bytes.

**9. Sign in from the editor.** Open the coin count in the top bar; there is a
Sign in there once `config.js` is filled in. Or from a shell:

```
python -m mangatl.account signup you@example.com
python -m mangatl.account                       # who am I, and how many coins
```

Until a project is configured the editor keeps using `~/.mangatl/wallet.json`,
exactly as it did — which is what a checkout with no billing behind it should
do.

## The prices

A hundred coins is a dollar of face value — see `mangatl/coins.py`, where every
price is a real provider cost, doubled. So the smallest pack is exactly face
value and everything else is a discount on it:

| price | coins | per $ | over face |
|---|---|---|---|
| $4.99 | 500 | 100.2 | face |
| $9.99 | 1,050 | 105.1 | +5% |
| $19.99 | 2,150 | 107.6 | +7.6% |
| $49.99 | 5,400 | 108.0 | +8% |

**There is no subscription.** lee: *"fuck teh subcription, it too omplicated
jus have teh pacjks"*. Which took with it the monthly allowance, the ceiling
over it, the expiry date and the second balance that existed to hold the
perishable half — and every question those raised: what happens when somebody
switches plan, cancels, buys a pack while subscribed, or simply does not use
this month's coins. None of it exists.

What is left is one sentence: **coins are bought outright and never expire.**

Packs climb in value because buying more at once is the only concession a
one-off purchase can make. Nothing is ever sold below face value — a hundred
coins is a dollar, and a test fails if any price crosses that line.

## What a run costs, and who pays for it

The editor takes the whole price of a run when the button is pressed, and gives
back the pages it never reached — lee: *"make teh edit remove the coins when
the person click teh button and if they cancel teh job it shoud refund them the
amount for teh pages that werent done"*. On an account that is two calls:

```
spendCoins  {coins, what, page, run}     once per run, `run` makes it once
refundCoins {coins, run}                 never more than that run took
```

`run` is a fresh id per run of a step. It is what stops a request that timed
out *after arriving* being paid for twice, and it is what a refund is measured
against — so a client that calls `refundCoins` with any number it likes gets
back nothing it did not pay.

## Still to build

- the rules suite has still never been executed here — `npm run test:rules` on
  a machine that can download the emulator
- the account page's ledger shows the last fifty lines; older ones are in
  Firestore and nothing reads them yet
