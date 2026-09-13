"""Deleting an account - on the website only, warned and asked twice.

lee: *"can we have a delete account button"*, and then *"delete account shoud
only happen on teh website and add a warning that its perminmt and add a secons
are yu sure message"*.
"""
from where import PKG

SITE = (PKG / "site" / "account.html").read_text(encoding="utf-8")
JS = (PKG / "static" / "js" / "coins.js").read_text(encoding="utf-8")
FN = (PKG / "firebase" / "functions" / "index.js").read_text(encoding="utf-8")


def test_the_website_warns_that_it_is_permanent_and_asks_twice():
    flat = " ".join(SITE.split())
    assert "This is permanent." in flat and "none of it can be brought back" in flat
    assert 'id="delWord"' in SITE and "if ($('delWord').value.trim() !== 'DELETE')" in SITE
    assert 'id="delVeil"' in SITE and "Are you sure?" in SITE
    assert "Yes, delete it forever" in SITE and "No, keep my account" in SITE
    first = SITE[SITE.index("$('delGo').onclick"):SITE.index("$('delYes').onclick")]
    assert "deleteAccount" not in first, "the first button only opens the second question"
    assert "setTimeout(() => $('delNo').focus(), 60)" in first, "the safe answer has the focus"
    yes = SITE[SITE.index("$('delYes').onclick"):]
    assert "call('deleteAccount')({ confirm: 'DELETE' })" in yes and "signOut(auth)" in yes


def test_the_app_has_no_delete_button_only_the_way_to_the_website():
    from mangatl import account
    assert "deleteAccount" not in JS and "do: 'delete'" not in JS and "do:'delete'" not in JS
    assert "function acctDeleteOnSite(" in JS and "walletOpenUrl('https://mangatct.com/account')" in JS
    assert 'onclick="acctDeleteOnSite()"' in JS[JS.index("async function renderAccount("):]
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    assert 'do == "delete"' not in src
    assert not hasattr(account, "delete_account")


def test_the_account_service_deletes_everything_but_the_free_coin_note():
    body = FN[FN.index("export const deleteAccount = onCall("):]
    body = body[:body.index("\n});\n")]
    assert "must(req.auth)" in body and "!== 'DELETE'" in body
    assert "db.recursiveDelete(userRef(uid))" in body
    assert "usernames/" in body and "collection('hands').where('uid', '==', uid)" in body
    assert "getAuth().deleteUser(uid)" in body
    assert body.index("recursiveDelete") < body.index("deleteUser"), "the sign-in goes last"
    assert "welcomed" not in body, "kept, so signing up again does not pay the free coins twice"
