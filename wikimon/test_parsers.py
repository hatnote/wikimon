# -*- coding: utf-8 -*-

# Not really real tests, but some real/contrived IRC messages are
# handy for manual testing.

msgs = ['[[List of My Little Pony characters]]  http://en.wikipedia.org/w/index.php?diff=601611011&oldid=601609204 * Anon126 * (-81) remove [[WP:SELFREF|self-reference]] in lead (this is specifically admonished in [[WP:LEADSENTENCE]]',
        '[[Wikipedia:WikiProject Anime and manga/Quality articles]]  http://en.wikipedia.org/w/index.php?diff=601611013&oldid=599866872 * CR4ZE * (+31) /* Good articles */ - Adding [[Big the Cat]]',
        "[[Northeastern Line (Thailand)]] !N http://en.wikipedia.org/w/index.php?oldid=601611015&rcid=645601343 * Mr.BuriramCN * (+6052) [[WP:AES|←]]Created page with '{{Infobox rail line  | box_width   = 300px  | logo        =  | logo_width  =  | logo_alt    =  | image       = Ubolstation.jpg  | imagesize = 300  | image_alt...'",
        '[[User talk:2001:558:6033:77:453B:B384:FEF:E2D9]]  http://en.wikipedia.org/w/index.php?diff=601611019&oldid=601610797 * Hertz1888 * (-492) Reverted 1 edit by [[Special:Contributions/67.98.243.15|67.98.243.15]]',
        '[[2001:_A_Space_Odyssey_(film)]]  http://en.wikipedia.org/w/index.php?diff=601611019&oldid=601610797 * Hertz1888 * (-492) Reverted 1 edit by [[Special:Contributions/67.98.243.15|67.98.243.15]]',
        '[[Special:Log/abusefilter]] hit  * Siddu808 *  Siddu808 triggered [[Special:AbuseFilter/527|filter 527]], performing the action "createaccount" on [[Special:UserLogin]]. Actions taken: none ([[Special:AbuseLog/10210680|details]])']


from parsers import parse_irc_message

for msg in msgs:
    parsed = parse_irc_message(msg)
    print parsed['ns'], '-', parsed['page_title']
