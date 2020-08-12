// read token from url
let url = new URL(window.location.href);
let oauth_token = url.searchParams.get('oauth_token')
let oauth_verifier = url.searchParams.get('oauth_verifier')

if (!(oauth_token && oauth_verifier)) {
    window.location.replace('https://t.me/my_daily_twitter_bot')
}

let tgMessageBox = document.getElementById('telegramMessage');
let boxText = tgMessageBox.getAttribute('value')
boxText = boxText.replace('OAUTH_TOKEN', oauth_token).replace('OAUTH_VERIFIER', oauth_verifier)
tgMessageBox.setAttribute('value', boxText)

// implement copy to clipboard with visual tooltip indicator
$('#copyToClipboardButton').tooltip()
document.getElementById('copyToClipboardButton').onclick = event => {
    let text = tgMessageBox.getAttribute('value')

    if (!navigator.clipboard) {
        try {
            tgMessageBox.focus();
            tgMessageBox.select();
            let successful = document.execCommand('copy');
            if (successful) {
                $(event.target).attr('title', 'Copied!').tooltip('show');
                $(event.target).attr('data-original-title', 'Copied!').tooltip('show');
                $(event.target).attr('title', 'Copy to clipboard');
                $(event.target).attr('data-original-title', 'Copy to clipboard');
            }
        } catch (err) {
            console.error('Unable to copy to clipboard', err);
        }
        return
    }

    navigator.clipboard.writeText(text).then(() => {
        $(event.target).attr('title', 'Copied!').tooltip('show');
        $(event.target).attr('data-original-title', 'Copied!').tooltip('show');
        $(event.target).attr('title', 'Copy to clipboard');
        $(event.target).attr('data-original-title', 'Copy to clipboard');
    })
}