List:
1. make everything configrable in an initial interactive menu that will create a local conf file - that in it the configuration to what to start will be present (backend/frontend/n8n/supabase/redis etc - also initial ports and port jumps), I do not want to rely on preconfigured file - I want if the file is missing to configure it in a conf window that will open straight away (it should be using the same style menu we've been using for --plan for example - but deeper and more thorough)

1a. Also add a --init that will open it even though it already exists and will allow us to edit current configurations

2. Refactor all the depandancies part - where it'd be easy for new developers to add new depandancy modules (let's say kafka for example) - so it'd be modular

3. Restracture files and create directories to conform to best practices and make the project have a resonable file stracture and directories

4. spot tasks that are not needed/repatative, find functions that repeat themseleves in a couple of files (if present)

5. Build a premade docker compose that would allow us to run depandancies without using client's one (it should be a stable one that is present in our own repository for every depadacy we have)

6. Dig deep, and understand how we could optimize starting up of the script, wether it is normal main run, main resume, tree tree run/plan run, or plan/tree resume - use our current debugging code - if needed exxtend furture - there's a lot of time to shave off there

7. add super extensive docs, please document both docs for devs and users, make docs for users super straight forward and friendly

8. could you think of a wiser way to handle all the ports rather than the X amount of port bump? Maybe it is the best solution, I am not sure - I just want you to think deep if it's the case or not

9. fix selection colour

11. move ./test-results/ to the /tmp directory where all the states and everything else is stored

12. fix --plan selection
