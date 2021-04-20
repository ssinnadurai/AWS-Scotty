import boto3
import os
import json
from slackclient import SlackClient


def validate_table(table_name):
    tableExistFlag = False
    client = boto3.client('dynamodb')
    paginator = client.get_paginator('list_tables')
    pages = paginator.paginate()
    for page in pages:
        for table in page['TableNames']:
            if table.lower() == table_name.lower():
                tableExistFlag = True
    return tableExistFlag


def getSlackWorkspaceId(slack_client):
    id = None
    response = slack_client.api_call("team.info")
    # pprint(response)
    if 'team' in response:
        id = response['team']['id']
    return id


def getSlackMember(slack_client, userId):
    response = slack_client.api_call("users.list")
    for member in response['members']:
        try:
            if member['id'] == userId:
                emailValue = member['profile']['email'].split('@')
                return emailValue[0]

        except KeyError:
            return None

    return None


def message_handler(message):
    error_message = {
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
    return error_message


def removeBlacklist(client, removeBlacklistData, type, tableName):
    type = type.replace(" remove ", "_")

    row = client.get_item(
        TableName=tableName,
        Key={'key': {'S': type}}
    )

    if 'Item' in row:
        # Turn the string to list to remove the data easily
        data = row['Item']['data']['S'].split(",")
        if removeBlacklistData in data:
            data.remove(removeBlacklistData)
        else:
            return False
        # turn it back into a string
        data = ",".join(data)

        # if the row exists then set the value to EMPTY
        if data == "":
            data = "EMPTY"

        client.put_item(
            TableName=tableName,
            Item={'key': {'S': type}, 'data': {'S': data}}
        )
        return True
    else:
        # row doesn't exist yet; therefore no table or use has been blacklisted
        return False


def addToBlacklist(client, blacklistData, type, tableName):
    # get the blacklist for user from dynamoDB

    type = type.replace(" ", "_")

    row = client.get_item(
        TableName=tableName,
        Key={'key': {'S': type}}
    )
    if 'Item' in row:
        # if the row exists. "EMPTY" is when the row had data at one point in time but was removed
        data = row['Item']['data']['S']

        if data.lower() == 'EMPTY':
            data = blacklistData
        else:
            if blacklistData in data.split(","):
                return False

            data += "," + blacklistData

        client.put_item(
            TableName=tableName,
            Item={'key': {'S': type}, 'data': {'S': data}}
        )

    else:
        # if the data row is new or if row was delete
        client.put_item(
            TableName=tableName,
            Item={'key': {'S': type}, 'data': {'S': blacklistData}}
        )

    return True


def display(client, tableName, type=None):
    if type == 'user':
        rowName = 'blacklist_user'
    elif type == 'table':
        rowName = 'blacklist_table'
    else:
        rowName = 'None'

    row = client.get_item(
        TableName=tableName,
        Key={'key': {'S': rowName}})

    if type == 'user':
        if 'Item' in row:
            data = row['Item']['data']['S']
            if data == 'EMPTY':
                return message_handler('No users have been blacklisted')

            displayVariable = '\n'.join(data.split(','))
            displayMessage = 'The users currently blacklisted are:\n' + displayVariable
            return message_handler(displayMessage)
        else:
            return message_handler('No user has been added to the blacklist')
    elif type == 'table':
        if 'item' in row:
            data = row['Item']['data']['S']
            if data == 'EMPTY':
                return message_handler('No table have been blacklisted')

            displayVariable = '\n'.join(data.split(','))
            displayMessage = 'The tables currently blacklisted are:\n' + displayVariable
            return message_handler(displayMessage)
        else:
            return message_handler('No table has been added to the blacklist')
    elif type is None:
        rows = client.batch_get_item(
            RequestItems={
                tableName: {
                    "Keys": [
                        {"key": {"S": "blacklist_user"}},
                        {"key": {"S": "blacklist_table"}}
                    ]
                }
            }
        )

        if rows['Responses'][tableName] == []:
            print("NO USERS OR TABLES has been set")

        Data = rows['Responses'][tableName]
        displayUser = ''
        displayTable = ''
        user_data='EMPTY'
        table_data='EMPTY'
        for data in Data:
            if data['key']['S'].lower() == 'blacklist_user':
                user_data = data['data']['S']
                displayUser = 'Users currently blacklisted are:\n' + '\n'.join(data['data']['S'].split(','))
            elif data['key']['S'].lower() == 'blacklist_table':
                table_data = data['data']['S']
                displayTable = 'Tables currently blacklisted are:\n' + '\n'.join(data['data']['S'].split(','))
        if user_data == 'EMPTY' and table_data == 'EMPTY':
            return message_handler('No Users or Tables have been blacklisted')
        displayMessage = displayUser + "\n\n" + displayTable
        return message_handler(displayMessage)


def help():
    message = "Blacklist has 3 different functionality: adding users or tables to the blacklist, removing users or tables from the blacklist and displaying all users and tables currently blacklisted." \
              "\n\n*_Blacklist Command_*" \
              "\n\tblacklist user <@slack user>" \
              "\n\tblacklist table <table name>" \
              "\n\tblacklist remove table <table name>" \
              "\n\tblacklist remove user <@slack user>" \
              "\n\tblacklist show or blacklist show user or blacklist show table"
    return message_handler(message)


def lambda_handler(event, context):
    print(json.dumps(event))
    userId = ""
    client = boto3.client('dynamodb')
    tableName = os.environ['dynamoDBTable']

    # Find who's requesting the to black list
    usersList = os.environ['usersList'].split(',')
    usersList = [users.strip() for users in usersList]

    # find who they are? Get the slack account id
    sc = SlackClient(os.environ['api_token'])
    workspace_id = getSlackWorkspaceId(sc)
    userId_split = event['userId'].split(":")
    if userId_split[1] == workspace_id:
        userId = userId_split[2]

    requestUserID = getSlackMember(sc, userId)
    # if they got permission then all processed to black listing
    if requestUserID.lower() in usersList:
        if event["inputTranscript"].lower() == 'blacklist help':
            return help()
        type = event['currentIntent']['slotDetails']['types']['originalValue']
        command = event['inputTranscript'].split(type)
        # what type of blacklisting they're attempting
        requestType = {'blacklist user', 'blacklist remove user', 'blacklist table', 'blacklist remove table',
                       "blacklist show"}
        blacklistRequestType = command[0].strip().lower() + " " + type.strip().lower()
        # use command[0] to see if it one of the 4 type of request they can ask
        if blacklistRequestType not in requestType:
            return message_handler("Invalid Request!")

        if blacklistRequestType.lower() == 'blacklist user' or blacklistRequestType.lower() == 'blacklist remove user':
            # Find the slack account
            user = command[1].strip().strip('<@').strip('>')
            id = getSlackMember(sc, user)

            if blacklistRequestType.lower() == 'blacklist user':
                if id is None:
                    return message_handler("User is not a member of this slack workspace.")

                if addToBlacklist(client, id, blacklistRequestType, tableName) is False:
                    return message_handler("This user has already been blacklisted.")
                else:
                    return message_handler(id + " has been blacklisted.")

            if blacklistRequestType.lower() == 'blacklist remove user':
                if removeBlacklist(client, id, blacklistRequestType, tableName) is False:
                    return message_handler("The user has not been blacklisted")
                else:
                    return message_handler(id + " has been removed from the blacklist")

        elif blacklistRequestType.lower() == 'blacklist table' or blacklistRequestType.lower() == 'blacklist remove table':
            blacklistTable = command[1].strip()
            validatedTable = validate_table(blacklistTable)

            if validatedTable is True:
                if blacklistRequestType.lower() == "blacklist table":
                    if addToBlacklist(client, blacklistTable, blacklistRequestType, tableName) is False:
                        return message_handler("This table has already been blacklisted.")
                    else:
                        return message_handler(blacklistTable + " has been blacklisted.")

                if blacklistRequestType.lower() == 'blacklist remove table':
                    if removeBlacklist(client, blacklistTable, blacklistRequestType, tableName) is False:
                        return message_handler("The table has not been blacklisted")
                    else:
                        return message_handler(blacklistTable + " has been removed from the blacklist")
            else:

                return message_handler(blacklistTable + " Does not exist in dynamoDB.")

        elif blacklistRequestType.lower() == "blacklist show":
            displayType = command[1].strip().lower()
            if displayType == "user":
                return display(client, tableName, displayType)
            elif displayType == "table":
                return display(client, tableName, displayType)
            elif displayType == '':
                return display(client, tableName)
            else:
                return message_handler("I didn't understand your request.")
    else:
        return message_handler("You are not allowed to Blacklist.")
