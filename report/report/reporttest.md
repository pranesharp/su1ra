6/10/26

(1 ) Fresh start
![alt text](image.png) on modes seems fine.

(2 ) I put in the models in settings - loadouts - and then restart the app
![alt text](image-2.png) on settings : Models NOT selected in the loadouts at all - the model names should be present in --select-model-- but THEY ARENT. The context i set for code model should be set to 17000 that i personally set and it said autosaved on top. but after restart (that i did) its set to 50k again.

(3 ) ![alt text](image-3.png) this happens as if an instance is already runnning (MADE NEW CHAT). MAYBE - when i make new chat, the previous chat does not get turned off, and also previously some time ago the app would auto make new chats on startup, now it opens on past chat open prior to closing the app.
![alt text](image-4.png) memory still occpied after closing su1ra???
I restart su1ra. then on chat i type command /eject in su1ra. ![alt text](image-5.png) this happens. hence the server was still on even after i closed app AND YET MY MEMORY IS STILL OCCUPIED. Okay i shall manually terminate 2 processes called :![alt text](image-7.png) , wow so now memory drops : ![alt text](image-8.png)

(4 ) Okay now i open su1ra, it auto starts server. still in older chat so i start new chat, this is the modes and all : ![alt text](image-10.png). 
now i will converse and query (gemma4 is auto selected BUT there is no model in loadouts. ![alt text](image-11.png)):  IN same chat alright? ![alt text](image-12.png) 
again i turned off app, and manually terminated the service from tskmgr . 

(5 ) restart su1ra, start new chat - since i always get to old chat, then typ in  /code ![alt text](image-13.png), opened ide, but wrong model? so loadout isnt right? and ctx is supposed to be 17 or 16k idr whoich one i selected. and then it says thinking on. but on top left it says think off. and when running model. the model does NOT do thinking. it reads sysprompt still, its supposed to in /code, but it still does in /casual. BUT now i perform /modes after typing /code okay : ![alt text](image-14.png) it knows its code mode, but the model isnt right at all.

the loadout system is what it feels like to be completely superfecial, same with the modes and startup and turn off issues.


PAST ISSUES ^^^^ iGNORE THEM WILL WRITE NEW DEBUGGING / BUG REPORTS AFTER NEW CHANGES.
