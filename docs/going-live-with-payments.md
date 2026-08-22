# Taking payments live

Test mode and live mode are two separate worlds inside one Stripe account.
Nothing crosses between them: not a key, not a product, not a price id, not a
webhook secret, not a customer. So going live is not a switch - it is doing the
setup a second time, in the other world, and pointing four things at it.

**Read the whole page before starting.** Step 3 is the one people miss, and it
does not fail until a real customer is holding a card.

---

## What has to be true before any of it

* **The Stripe account is activated.** Business details, and a bank account to
  be paid into. Live mode is refused until it is.
* **Managed Payments is enabled and its terms accepted** -
  <https://dashboard.stripe.com/settings/managed-payments>. This is separate
  from activating the account, and this integration cannot work without it:
  `index.js` sets `managed_payments: { enabled: true }` on every Checkout
  Session.

Managed Payments means **Stripe is the merchant of record**. They calculate,
collect, file and remit sales tax, VAT and GST in 80+ countries and carry the
fraud and dispute load. What it costs you, besides the fee: the customer's
statement reads `LINK.COM* MANGATCT`, their receipt comes from Link, and
refunds can be granted by Stripe without asking you if a support escalation
goes 48 hours unanswered. `charge.refunded` is handled - see `handle()` - so
coins come back out when that happens.

---

## 1. Switch the Dashboard to live mode

Top-left toggle. Everything below is done with it OFF sandbox. A price id
created in test mode is invisible to a live key, which fails as
`No such price` - this is the single most common way this goes wrong.

## 2. Create the four packs, in live mode

<https://dashboard.stripe.com/products> → **Add product**, four times. The
names are yours; the numbers are not - they must match `PACKS` in
`firebase/functions/purse.js`, because that is what grants the coins:

| id | price | coins |
|---|---|---|
| `pack1` | $4.99 | 500 |
| `pack2` | $9.99 | 1050 |
| `pack3` | $19.99 | 2150 |
| `pack4` | $49.99 | 5400 |

One-time, not recurring. lee: *"fuck teh subcription, it too omplicated jus
have teh pacjks"*.

Keep the four `price_...` ids. Not the `prod_...` ids - the price is what a
Checkout Session takes.

## 3. Give every product a tax code - the step that is easy to miss

Managed Payments cannot calculate tax for a product it cannot categorise, and a
product with no eligible tax code is **refused at checkout, in live mode
only**. Nothing in test mode tells you.

**Set it once, as the preset**, rather than four times by hand:
<https://dashboard.stripe.com/settings/managed-payments> → Tax settings →
**Preset tax category** → `Digital products > Software > Software as a
service`. It must read *✓ Eligible for Managed Payments*. Products made after
it inherit it, so the four packs are covered before they exist, and the same
page tells you *All of your products are eligible* when nothing is left out.

The per-product way is still there if one ever needs its own: **⋯ → Edit
product → Product tax code**.

### And the tax behaviour - set this, it is not the default

**Tax is inside the price.** lee: *"also make the price will include the
tax"*. A customer pays exactly $4.99 in Ohio, in London and in Sydney; Stripe
takes each country's tax out of that figure rather than adding it on top. You
net less where tax is high - about $4.15 of a $4.99 sale at 20% VAT - and
nobody is ever surprised at checkout. That is the trade, and it is the right
way round for a $4.99 impulse buy.

**Stripe's default is the opposite**, so this has to be set, in one of two
places:

* once for the account - Managed Payments settings → Tax settings → **Include
  tax in prices** → **Yes**, which every price made afterwards inherits; or
* per price, `tax_behavior: inclusive`, when you create it.

Not **Automatic**: that one includes tax for most currencies and EXCLUDES it
for USD and CAD, so a US customer would be charged on top while a French one
was not. Same page, same price, two different promises.

Do it before the prices exist. **A price's tax behaviour is fixed once it has
been used**, so changing your mind later means creating four NEW prices and
re-running `seed.js`, not editing the four you have.

And check the page you set it on is in **live** mode. Setting it in sandbox
leaves live on the default, and the first thing you would hear about it is a
receipt.

> ### If you copied the products over from test mode
>
> **A copied price brings its original tax behaviour with it.** The account
> setting applies to prices made AFTER it, and a price copied from sandbox was
> made before - so it most likely arrives `unspecified`, which Managed Payments
> reads as "add tax on top". The products look right, the category says
> Eligible, and the customer is charged more than the page said.
>
> Open each of the four prices and read it: it must say the amount **includes**
> tax. Where it does not, add a NEW price to the same product, archive the old
> one, and use the new `price_...` id in `seed.js`. A price's tax behaviour
> cannot be edited once it exists.

Check it before you leave the Dashboard: open one of the four prices and it
should say the amount **includes** tax. If it does not, delete it and make it
again - that is cheaper than finding out from a customer's receipt.

## 4. The live secret key

<https://dashboard.stripe.com/apikeys> → reveal the secret key. It begins
`sk_live_`.

```bat
cd C:\Users\leema\OneDrive\Documents\mangatl
firebase functions:secrets:set STRIPE_KEY
```

Paste it at the prompt. It never touches a file and never touches the
repository.

## 5. Deploy, so the webhook has an address

```bat
firebase deploy --only functions
```

When it finishes it prints the function URLs. The one you want is
`stripeWebhook`, and it looks like this:

```
Function URL (stripeWebhook(us-central1)): https://stripewebhook-wyfd5lpvba-uc.a.run.app
```

**Use the line it prints, not one written down here.** These are second-
generation functions, which run on Cloud Run and are given a `run.app` address
with a random-looking piece in the middle. It belongs to this deployment; it is
not guessable and it is not the same as the `cloudfunctions.net` form the older
functions use.

## 6. The live webhook

<https://dashboard.stripe.com/webhooks> → **Add endpoint** → that URL.

Subscribe to exactly two events. Both are handled; anything else is noise the
function answers 200 to and ignores:

* `checkout.session.completed` - the coins go in
* `charge.refunded` - the coins come back out

Then **Reveal** the signing secret (`whsec_...`) and:

```bat
firebase functions:secrets:set STRIPE_WEBHOOK_SECRET
firebase deploy --only functions
```

The second deploy is not optional. A secret is bound to a function at deploy
time, so setting it changes nothing until the function is deployed again.

> **`Unhandled error cleaning up build images`** at the end of a deploy is not
> a failed deploy - `Deploy complete!` on the next line is the truth. It means
> the container images the build produced were left in the registry instead of
> being swept up. They cost cents a month, and the next successful deploy
> usually clears them; if the message keeps coming back, delete them at
> <https://console.cloud.google.com/gcr/images/mangatctproject/us/gcf>.
> Nothing about the running function depends on them.

> If the webhook rejects everything with `bad signature`, the function logs the
> **length** of the secret it is holding and the size of the body it got - never
> the secret itself. A length of 0 means the secret is not bound; a length four
> longer than it should be usually means a newline or a pair of quotes came
> along with the paste.

## 7. Tell Firestore the live price ids

The Stripe ids live in the database, not in the code, precisely so that this
step does not need a deployment:

```bat
cd firebase\functions
node seed.js price_pack1=price_LIVE1 price_pack2=price_LIVE2 ^
             price_pack3=price_LIVE3 price_pack4=price_LIVE4
```

Anything you leave out keeps what is already there, so it is safe to run again
after fixing one.

It needs application-default credentials once:

```bat
gcloud auth application-default login
```

## 8. Check `SITE_URL`

`firebase/functions/.env.mangatctproject` currently says:

```
SITE_URL=https://mangatctproject.web.app
```

That is where a paying customer is sent after checkout. It is right for today.
The day `mangatct.com` resolves, change this line, redeploy the functions, and
add the domain under **Authentication → Settings → Authorized domains** - sign
in refuses to work on a domain that is not on that list, and the checkout
button is behind sign in.

---

## 9. Prove it with real money

Test mode cannot tell you whether step 3 was done. Only a live payment can.

1. Sign in on the live site with an account you can afford to spend on.
2. Buy **pack1** - $4.99, the cheapest thing that exercises the whole path.
3. Watch the coin count in the editor's top bar go up by 500.
4. <https://dashboard.stripe.com/webhooks> → your endpoint → the delivery
   should be `200`. If it is `400`, the signing secret is wrong; if `500`, the
   function threw and the log says why.
5. **Refund it** from the Dashboard, and watch the 500 coins come back out.
   That is `charge.refunded`, and it is the half nobody tests until it happens
   to a customer.

A retry is safe: every grant is keyed on the Stripe object's id under
`granted` on the user, so a webhook delivered twice credits once. That is worth
knowing because Stripe *will* deliver twice eventually.

---

## What stays test-mode

Nothing in the code. There is no test/live branch anywhere - the key decides,
and the key is a secret set outside the repository. `site/config.js` holds no
Stripe key at all: checkout is a redirect to a session URL the function makes,
so the browser never sees one.

## If you want to go back

Set `STRIPE_KEY` to the test key, re-run `seed.js` with the test price ids,
redeploy. Nothing else remembers which world it was in.
