import subprocess

a = int(input("1)Send Message\n2)Send Message To Group\n3) Check Group Ids"))


def send_quick_message(number_or_group_id: str, message: str):
    subprocess.run(['node', 'bot.js', number_or_group_id, message])

if a == 1:
    send_quick_message('923361915333', 'Hello from Python 🚀')
elif a == 2:
    send_quick_message('HwM6um1c0Bg9nIkixqdCG9@g.us', 'Hello group!')
else:
    send_quick_message('group', '')  # This will print all group names & IDs
