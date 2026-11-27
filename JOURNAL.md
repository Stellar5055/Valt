# My Journal for Valt


## Day 1 -  23-11-26

- I got the plan in my mind, and used an ai agent to plan it out and form a spec. then i spend some time changing ideas and just forming a solid plan with stages to building it. I did this at night, and didnt do any commits yet and didnt write any code

## Day 2 -  24-11-26

- In the morning, i got some time to code, started the actual coding wrote crypto.py mostly by myself but used chatgpt for learning how to use argon and these tools which i havent used before. Then told my agent to make a test for this in tests/ and it passed, than did a commit after that. Then i tried to do safes.py which was like the locking unlocking flow, i tried this on my own, agent found a lot of bugs. i understood them, some i fixed others the agent fixed. then i told agent to write the test for safes, it didnt pass first try. agent told its a logic error, i understood it and then fixed it with the agent. then commited

- At night, i finished until stage 5. stage 5 was hard for me, especially since the logics where confusing, i understood a lot with the help of chatgpt and then after a lot of trial and error and testing, i fixed it. the flow was similar - agent explains what to do in a stage, i code it and if its hard, i ask chatgpt for explaining and stuff, then i test it manually, most of the time there are errors, i fix, and for logical errors also i keep iterating, and after that, i ask the agent to evaluate. it finds bugs and fixes them. when no bugs, it make the test file inside tests/ and runs it. if all pass, i commit.

## Day 3 - 25-11-36

- Didnt do anything today, was busy with school stuff

## Day 4 - 26-11-26

- I finished stage 6 in the morning - this was also hard - harder than stage 5, there were soo much like new stuff that i havent learnt - i used chatgpt help for some parts understanding stuff, but finally did it. it also took many iterations of testing small stuff manually with test folders etc and its done, commited and the agent wrote tests.

- During the afternoon and evening, i finished stage 7 and 8. both were very satisfiyiying, on stage 8 almost 0 errors i came across, 7 had a few, fixed them. after stage 8, i spent liek 20 minutes like testing every single use case possible - (not literally everything but the most common ones). that revealed one error taht i fixed. now everything is perfect till stage 8. then i did stage 9. this was fully done with my agent because it was small and only added some cli commands like add containers, change password, remove containers etc and needed no like new backend etc.

- Now stage 10. this is a free stage where i just add features /small things when i feel like it. in this part, this much is vibecoded - first i added a progressbar (not an actual bar, just percentage and eta). then made the progressbar also show current container being packed/unpacked, then added thsi where if no container label is added, it defaults to the folder name. this much was step 1 of this stage. after that, i setup pyinstaller with the pyinstaller's spec making it so that when i run a build.bat, it builds a valt.exe

- Then i decided to try to add gui. i used Winrar's extract gui as style reference then told agent to integrate a ui with ttk, and fiirst there were errors, after fixing them, it looked ok but functionality was kind of bad, like some features didnt work. I went to sleep and decided to work on it tomorrow


## Day 5

- First i changed the pyinstaller spec to make a valt.exe and valt-cli.exe, the cli one has no gui, its slightly smaller(normal - 15MB, cli - 12MB) i fixed another cli bug i found which is interactive mode stopped working, then i worked on deslopping and fixing the gui

- Then worked a lot - vibecoded most of this, on adding features, changing a lot of things, all tiny tiny things - like .valt file association, GUI compacting and redesigning, start menue entry, scoop and irm distribution, github ci with auto release building, etc, and towards the end, also added logo for the app and the .valt files - both were made with ai, implementaed them. then i did some research on options to have a shorter install command, but couldnt find a reliable free option, so decided to leave the long command for now. So project is almost done, now i have to write readme, make a demo video, and im done

- Here is the semo video i made:

<video controls src="Demo.mp4" title="Demo"></video>