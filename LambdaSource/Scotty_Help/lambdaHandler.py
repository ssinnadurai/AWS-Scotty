from slackclient import SlackClient
import os


def message_handler(message):
    messages = {
        'sessionAttributes': {},
        "dialogAction": {
            "type": "Close",
            "fulfillmentState": "Fulfilled",
            "message": {
                "contentType": "PlainText",
                "content": message
            },
        }
    }
    return messages


def help_overview(user):
    message = ""
    message += "I can perform the following actions:\n"
    message += "\n\t*_Request Table Access_*"
    if user in os.environ['userList'].split(','):
        message += "\n\t*_Blacklist Users / Tables_*"
    message += "\n\n"
    message += "You can ask for help on specific commands:\n"
    message += "\n\thelp table access"
    if user in os.environ['userList'].split(','):
        message += "\n\thelp blacklist"
    message += "\n\nFor additional assistance please contact a member of *_Team SRE_*"
    return message


def blacklistHelp():
    message = "Using the blacklist command, you can add or remove users or tables to/from the blacklist, or show the current blacklist." \
              "\n\n*_Blacklist Command_*" \
              "\n\tblacklist user <@slack user>" \
              "\n\tblacklist table <table name>" \
              "\n\tblacklist remove table <table name>" \
              "\n\tblacklist remove user <@slack user>" \
              "\n\tblacklist show or blacklist show user or blacklist show table"
    return message

def tableAccessHelp():
    message = (
        "*_Request Command_*"
        "\n\tTo request access to tables use the following command: \n\t\t*Request access to {table name(s)} until {YYYY-MM-DD}*\n\t\t*Access to {table name(s)} {YYYY-MM-DD}*"
        "\n\n"
        "*_Specifics_*"
        "\n\t *_Table _*"
        "\n\t\tMultiple tables can be requested by *using a comma separated list* for table names and *full table name* must be provided"
        "\n\t\tTables can be requested by using the table suffix, but only one table can be requested at a time"
        "\n\n\t *_Request Period_*"
        "\n\t\tAccess is limited to a maximum 7 of days"
        "\n\t\tDuration can be specified by day or date, eg:"
        "\n\t\t\trequest access until EOD today by using today or 2019-01-01 "
        "\n\t\t\trequest access until EOD Wednesday by using Wednesday"
        "\n\t\t\trequest access until EOD on the 19th by using YYYY-MM-19"
        "\n\n*_Abort Command_*"
        "\n\t*Cancel* to stop the current request."
        "\n\n*_Examples_*:"
        "\n\t*Request access to table 1, table 2, table 3 until tomorrow*"
        "\n\t*Access to table 1, table 2, table 3 2019-01-01*"
        "\n\nFor additional assistance please contact a member of *_Team SRE_*"
        "\n\n Display Table Access"
        "\n\tDisplay the current table access and expiration date:"
        "\n\t\tCommand: show table access"
        "\n\nFor additional assistance please contact a member of *_Team SRE_*")
    return message


def getSlackWorkspaceId(slack_client):
    id = None
    response = slack_client.api_call("team.info")
    # pprint(response)
    if 'team' in response:
        id = response['team']['id']
    return id


def getSlackMember(slack_client, userId):
    response = slack_client.api_call("users.list")
    # pprint(response)
    for member in response['members']:
        try:
            if member['id'] == userId:
                emailValue = member['profile']['email'].split('@')
                return emailValue[0]

        except KeyError:
            return None

    return None


def lambda_handler(event, context):  # event, context

    request = event['inputTranscript']

    slack_client = SlackClient(os.environ['api_token'])

    workspace_id = getSlackWorkspaceId(slack_client)

    requester = event['userId'].split(':')

    if requester[1] == workspace_id:
        userId = requester[2]

    user= getSlackMember(slack_client,userId).lower()

    if request.lower() == 'help':
        return message_handler(help_overview(user))
    elif request.lower() == 'help blacklist' :
        if user in os.environ['userList'].split(','):
            return message_handler(blacklistHelp())
        else:
            return message_handler('Only Team-SRE can access the blacklist')
    elif request.lower() == 'help table access':
        return message_handler(tableAccessHelp())
    else:
        return message_handler("I couldn't understand your request!")



