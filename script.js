// read token from url
let url = new URL(window.location.href);
let oauth_token = url.searchParams.get('oauth_token')
let oauth_verifier = url.searchParams.get('oauth_verifier')
let tgMessageBox = document.getElementById('telegramMessage');
let boxText = tgMessageBox.getAttribute('value')
boxText = boxText.replace('OAUTH_TOKEN', oauth_token).replace('OAUTH_VERIFIER', oauth_verifier)
tgMessageBox.setAttribute('value', boxText)

// implement copy to clipboard with visual tooltip indicator
$('#copyToClipboardButton').tooltip()
document.getElementById('copyToClipboardButton').onclick = event => {
    let text = tgMessageBox.getAttribute('value')

    navigator.clipboard.writeText(text).then(() => {
        $(event.target).attr('title', 'Copied!').tooltip('show');
        $(event.target).attr('data-original-title', 'Copied!').tooltip('show');
        $(event.target).attr('title', 'Copy to clipboard');
        $(event.target).attr('data-original-title', 'Copy to clipboard');
    })
}