# The four products, to paste into Stripe

<https://dashboard.stripe.com/products> → **Add product**, four times, in
**live** mode.

Three things have to be exactly right, and the rest is copy:

* **the price**, because `PACKS` in `firebase/functions/purse.js` grants coins
  by pack id and the two have to agree;
* **the tax code**, or Managed Payments refuses the sale at checkout in live
  mode — see `going-live-with-payments.md`;
* **tax behaviour: inclusive**, so $4.99 is what the customer pays anywhere in
  the world. This is not Stripe's default and cannot be changed after a price
  has been used.

The **name** is what appears on the customer's card statement, on their Link
receipt and in the Checkout Session — so it carries the brand and the size, not
a pack number. `pack3` means nothing on a bank statement.

The **description** is what they read on the checkout page with their card in
their hand. One line, what they get, no adjectives.

---

## 1 — `pack1`

**Name**

```
MangaTCT — 500 coins
```

**Description**

```
500 TCT Coins. About one 20-page chapter read and translated on a fast model. Coins never expire.
```

**Price** `$4.99` USD · one-time · **tax inclusive**

---

## 2 — `pack2`

**Name**

```
MangaTCT — 1,050 coins
```

**Description**

```
1,050 TCT Coins, at 105 to the dollar. Around two chapters end to end. Coins never expire.
```

**Price** `$9.99` USD · one-time · **tax inclusive**

---

## 3 — `pack3`

**Name**

```
MangaTCT — 2,150 coins
```

**Description**

```
2,150 TCT Coins, at 108 to the dollar. Four or five chapters, including a proofread pass on each. Coins never expire.
```

**Price** `$19.99` USD · one-time · **tax inclusive**

---

## 4 — `pack4`

**Name**

```
MangaTCT — 5,400 coins
```

**Description**

```
5,400 TCT Coins, at 108 to the dollar. A dozen chapters, or one long series read on the best models. Coins never expire.
```

**Price** `$49.99` USD · one-time · **tax inclusive**

---

## For every one of them

| field | value |
|---|---|
| Type | One-off (not recurring) |
| Currency | USD |
| Tax behaviour | **Inclusive** — the price includes tax |
| Product tax code | a digital-goods / SaaS code marked *Eligible for Managed Payments* |
| Statement descriptor | leave it — Managed Payments sets it, and the customer sees `LINK.COM* MANGATCT` |

Then copy the four **`price_...`** ids — not the `prod_...` ids — into:

```bat
cd firebase\functions
node seed.js price_pack1=… price_pack2=… price_pack3=… price_pack4=…
```

---

## Where the coin numbers come from

`firebase/functions/purse.js`. If you ever change a pack's size or price,
change it there and re-run `seed.js` — the pricing page draws itself from
`config/prices`, which `seed.js` writes, so the page cannot disagree with the
server about what a pack is.

What it does NOT write is the Stripe price. That has to be changed in the
Dashboard by hand, and the amounts have to be kept in step. A test holds the
page, `seed.js` and `purse.js` together; nothing can hold Stripe.

## About the "one chapter" claims

They are honest for a 20-page chapter on a mid-range model, read from the
figures in `coins.py`: a 23-page chapter with 213 boxes quotes at **91 coins**
on Gemini 3.6 Flash and **39** on Sonnet 5. Cleaning and typesetting cost
nothing — they run on the customer's own machine.

They are estimates, and the descriptions say "about" and "around" for that
reason. Do not tighten them into promises.
