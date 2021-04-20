import boto3
import os
import json
import botocore.errorfactory
import re
from datetime import date, datetime
from dateutil.parser import parse
from botocore.vendored import requests
from pprint import pprint
from slackclient import SlackClient


def get_policy_template():
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Action": [
                    "dynamodb:BatchGetItem",
                    "dynamodb:ConditionCheckItem",
                    "dynamodb:Scan",
                    "dynamodb:DescribeStream",
                    "dynamodb:Query",
                    "dynamodb:DescribeGlobalTableSettings",
                    "dynamodb:DescribeTable",
                    "dynamodb:DescribeGlobalTable",
                    "dynamodb:GetShardIterator",
                    "dynamodb:GetItem",
                    "dynamodb:DescribeContinuousBackups",
                    "dynamodb:DescribeBackup",
                    "dynamodb:GetRecords",
                    "dynamodb:DescribeTimeToLive"
                ],
                "Resource": [
                    "arn:aws:dynamodb:##REGION##:##ACCOUNT_NUMBER##:table/##TABLE_NAME##",
                    "arn:aws:dynamodb:##REGION##:##ACCOUNT_NUMBER##:table/##TABLE_NAME##/*"
                ],
                "Effect": "Allow"
            }
        ]
    }


def getSlackWorkspaceId(slack_client):
    id = None
    response = slack_client.api_call("team.info")
    # pprint(response)
    if 'team' in response:
        id = response['team']['id']
    return id


# This method check if the user email and parses it for the username if user doesnt not exist then it return None
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


# This method is called to get the iam team name the user is part of
# If the user is not in a team, it returns the iam user account
def getGroupIdentity(iam, name):
    groupName = os.environ['GroupName'].split(",")

    groups = iam.list_groups_for_user(
        UserName=name
    )

    indexgroups = groups['Groups']

    for index in indexgroups:
        if index['GroupName'] in groupName:
            return index['GroupName']
    return name


# if the provided table exists, create a policy or up-issue existing policy.
# otherwise, just return a template of the policy
def create_policy(iam, tableList, date, group, tableExistFlag=False):
    # Get the account ID from STS
    sts_client = boto3.client('sts')
    AccountId = sts_client.get_caller_identity()['Account']
    Region = os.environ['AWS_REGION']
    policy = None
    status = False
    existingAccess = ''
    resource_list = []

    policy_template = get_policy_template()

    for table in tableList:
        resource_list.append('arn:aws:dynamodb:' + Region + ':' + AccountId + ':' + "table/" + table)
        resource_list.append('arn:aws:dynamodb:' + Region + ':' + AccountId + ':' + "table/" + table + '/*')

    policy_template['Statement'][0]['Resource'] = resource_list
    print(json.dumps(policy_template))

    policyName = date + '-' + group

    if tableExistFlag:
        try:
            policy = iam.create_policy(
                PolicyName=policyName,
                PolicyDocument=json.dumps(policy_template)
            )
            status = True
        except botocore.errorfactory.ClientError:
            existing_policy = iam.get_policy(
                PolicyArn='arn:aws:iam::' + AccountId + ':policy/' + policyName
            )

            policyVersionsList = iam.list_policy_versions(
                PolicyArn=existing_policy['Policy']['Arn']
            )

            if len(policyVersionsList['Versions']) == 5:
                iam.delete_policy_version(
                    PolicyArn=existing_policy['Policy']['Arn'],
                    VersionId=policyVersionsList['Versions'][4]['VersionId']
                )

            existing_policy_version = iam.get_policy_version(
                PolicyArn=existing_policy['Policy']['Arn'],
                VersionId=existing_policy['Policy']['DefaultVersionId']
            )

            currentResource = existing_policy_version['PolicyVersion']['Document']['Statement'][0]['Resource']
            for i in range(0, len(currentResource), 2):
                existingAccess += currentResource[i][
                                  len('arn:aws:dynamodb:' + Region + ':' + AccountId + ':' + "table/"):] + ","
            existingAccess = "\n".join(existingAccess.split(",")[:-1])

            for item in resource_list:
                if item not in currentResource:
                    currentResource.append(item)
            policy_template['Statement'][0]['Resource'] = currentResource
            policy = iam.create_policy_version(
                PolicyArn=existing_policy['Policy']['Arn'],
                PolicyDocument=json.dumps(policy_template),
                SetAsDefault=True
            )
        print(policy)
    else:
        policy = policy_template

    return (status, policy, existingAccess)


# if policy is create or already exist then attach to the group or user
def attach_policy(iam, policy_created, group):
    try:
        Iam_Attach_policy = iam.attach_group_policy(
            GroupName=group,
            PolicyArn=policy_created['Policy']['Arn']
        )
    except botocore.errorfactory.ClientError:

        Iam_Attach_policy = iam.attach_user_policy(
            UserName=group,
            PolicyArn=policy_created['Policy']['Arn']
        )
    except botocore.errorfactory.ClientError:
        return False  # should never reach this statement
    return Iam_Attach_policy


# message the slack team channel as well as team-sre when policy is attached to the user or team
def messageToSlack(table_name, group, userId, date):
    slack_channel = '#' + group.lower()
    slack_format_table_name = ""
    notificationChannel = os.environ['notificationChannel'].split(",")
    pretext = 'READ Access has been granted to %s for the following table%s until EOD %s (requested by <@%s>):' % \
              (group, ('s' if len(table_name.split('\n')) > 1 else ''), date, userId)

    print(slack_channel)

    slack_message = {
        'channel': slack_channel,
        "attachments": [
            {
                "fallback": "Table Access",
                "color": "#2eb886",
                "pretext": pretext,
                "text": table_name
            }
        ]
    }

    _send_slack_message(slack_message)


    if slack_channel not in  notificationChannel:
        for channel in notificationChannel:
            slack_message = {
                'channel': channel,
                "attachments": [
                    {
                        "fallback": "Table Access",
                        "color": "#2eb886",
                        "pretext": pretext,
                        "text": table_name
                    }
                ]
            }
            _send_slack_message(slack_message)


# post message format that can be sent to slack
def _send_slack_message(slack_message):
    response = requests.post(
        os.environ['HookUrl'], data=json.dumps(slack_message),
        headers={'Content-Type': 'application/json'}
    )

    if response.status_code != 200:
        raise ValueError(
            'Request to slack returned an error %s, the response is:\n%s'
            % (response.status_code, response.text)
        )
    return response.status_code


def response_card_option(option_list):
    options = []
    for opt in option_list:
        options.append({'text': opt, 'value': opt})
    return options


def responseCard(title, subtitle, options):
    if not title:
        title = ' '

    genericAttachments = None

    if options is not None:
        genericAttachments = []
        N = 5
        # break down the list of options into a list of sub lists of length 5
        subList = [options[n:n + N] for n in range(0, len(options), N)]
        # For each sublist, create an attachment dict and append it to genericAttachments
        for i in range(0, len(subList)):
            attachment = {}
            attachment['title'] = title
            attachment['buttons'] = subList[i]
            if subtitle:
                attachment['subTitle'] = subtitle
            genericAttachments.append(attachment)

    response_card = {}
    response_card['contentType'] = 'application/vnd.amazonaws.card.generic'
    response_card['version'] = 1
    response_card['genericAttachments'] = genericAttachments
    return response_card


# validate the table entered by the user
def validate_table(table_name):
    blacklist = []
    client = boto3.client('dynamodb')
    row = client.get_item(
        TableName=os.environ['dynamoDBTable'],
        Key={'key': {'S': 'blacklist_table'}})
    if 'Item' in row:
        blacklist = row['Item']['data']['S'].split(',')

    tableExistFlag = False
    paginator = client.get_paginator('list_tables')
    pages = paginator.paginate()
    mlist = []
    partialflag = ''
    for page in pages:
        for table in page['TableNames']:
            if table.lower() == table_name.lower() and table_name.lower() not in [blacklist_table.lower() for
                                                                                  blacklist_table in blacklist]:
                tableExistFlag = True
            elif table.endswith(table_name) and "STAGE" not in table:
                foundTable = table
                if foundTable.lower() not in [blacklist_table.lower() for blacklist_table in blacklist]:
                    mlist.append(table)
                    partialflag = True

    if partialflag is True:
        return responseCard("Which one of the following " + table_name + " table are you looking for?", None,
                            response_card_option(mlist))

    return tableExistFlag


def elicit_slot(session_attributes, message, slot, slot_to_elicit, response_card=None):
    elicit_slot_message = {
        'sessionAttributes': session_attributes,
        "dialogAction": {
            "type": "ElicitSlot",
            "intentName": "Scotty_TableAccess",
            "slots": slot,
            "slotToElicit": slot_to_elicit,
            "message": {
                "contentType": "PlainText",
                "content": message
            },
            'responseCard': response_card
        }
    }
    return elicit_slot_message


def reprompt(session_attributes, message, slot):
    reprompt_message = {
        'sessionAttributes': session_attributes,
        "dialogAction": {
            "type": "ConfirmIntent",
            "intentName": "Scotty_TableAccess",
            "slots": slot,
            # "slotToElicit": slot_to_elicit,
            "message": {
                "contentType": "PlainText",
                "content": message
            }

        }
    }
    return reprompt_message


# send message via LEX Bot
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


def denyAccess(iam, tableList, eventDate, group, userId):
    status, denied_policy = create_policy(iam, tableList, eventDate, group, False)

    slack_message = {
        'channel': os.environ['notificationChannel'],
        "attachments": [
            {

                "fallback": "Request Denied!",
                "color": "#2eb886",
                "pretext": "Request was denied to <@" + userId + ">",
                "text": json.dumps(denied_policy, indent=4)
            }
        ]
    }
    _send_slack_message(slack_message)
    return message_handler(
        "You are not a member of a development team. Please contact a member of Team-SRE to request access.")


def display(iam,sc,id):
    user = getSlackMember(sc,id)
    group = getGroupIdentity(iam, user)
    if group not in os.environ['GroupName']:
        return message_handler("You are not part of a team!")


    sts_client = boto3.client('sts')
    AccountId = sts_client.get_caller_identity()['Account']
    Region = os.environ['AWS_REGION']

    pattern = re.compile(r'\d{4}-\d{2}-\d{2}-Team-\w')
    attachedPolicies = iam.list_attached_group_policies(
        GroupName= group
    )
    accessTo = ""

    for policy in attachedPolicies['AttachedPolicies']:
        existingAccess = ''
        policyDate = policy['PolicyName'].split('-Team')[0]
        if pattern.match(policy["PolicyName"]):
            getPolicy = iam.get_policy(
                PolicyArn=policy['PolicyArn']
            )
            defaultPolicy = iam.get_policy_version(
                PolicyArn=getPolicy['Policy']['Arn'],
                VersionId=getPolicy['Policy']['DefaultVersionId']
            )

            currentResource = defaultPolicy['PolicyVersion']['Document']['Statement'][0]['Resource']
            for i in range(0, len(currentResource), 2):
                existingAccess += currentResource[i][
                                  len('arn:aws:dynamodb:' + Region + ':' + AccountId + ':' + "table/"):] + ","
            existingAccess = "\n".join(existingAccess.split(",")[:-1])

            accessTo += group + " has access to the following table%s until EOD " % (
                's' if len(currentResource) / 2 > 1 else '') + policyDate + ":\n" + existingAccess + "\n\n"

    if accessTo == "":
        return message_handler("No access to table found!")
    else:
        return message_handler(accessTo)

def lambda_handler(event, context):  # event, context
    print(json.dumps(event))
    slack_client = SlackClient(os.environ['api_token'])
    iam = boto3.client('iam')

    # set counter
    session_Attributes = event["sessionAttributes"]
    if session_Attributes is None or session_Attributes == {}:
        session_Attributes = {
            "counter": 0,
            "validateCounter": 0,
            "dateCounter": 0,
            "TableString": "",
            "tableReprompt": "True"
        }
        counter = session_Attributes['counter']
        validateCounter = session_Attributes["validateCounter"]
        dateCounter = session_Attributes["dateCounter"]
        tablestring = session_Attributes['TableString']
        isReprompt = session_Attributes['tableReprompt']
    else:
        counter = int(session_Attributes['counter'])
        validateCounter = int(session_Attributes["validateCounter"])
        dateCounter = int(session_Attributes["dateCounter"])
        tablestring = session_Attributes['TableString']
        isReprompt = session_Attributes['tableReprompt']

    if event['inputTranscript'].lower() == 'cancel' or event['inputTranscript'].lower() == 'abort':
        return message_handler("You have cancelled the request to access dynamoDB")

    workspace_id = getSlackWorkspaceId(slack_client)

    # Get the user that sent the command
    userId = event['userId']
    userId_split = userId.split(':')

    # check if they're part of the correct workspace on slack
    if userId_split[1] == workspace_id:
        userId = userId_split[2]

    if event['inputTranscript'].lower() == "show table access":
        return display(iam,slack_client, userId)


    # the value the user entered for table and date
    table_name = event['currentIntent']['slots']['table']
    eventDate = event['currentIntent']['slots']['duration']

    # if date or table value has not been entered, then prompt to enter a value
    if table_name == None or event['currentIntent']['slotDetails']['table']['originalValue'].lower() == "table":
        if counter == 2:
            session_Attributes['counter'] = 0
            return message_handler("You have reached your attempt limit! Please try again or find a member of Team-SRE")
        elif event['inputTranscript'].lower() == 'access to' or event['inputTranscript'].lower() == 'request access to' or event['inputTranscript'].lower() == 'request access' :
            session_Attributes = {
                "counter": counter,
                "validateCounter": validateCounter,
                "dateCounter": dateCounter,
                "TableString": tablestring,
                "tableReprompt": isReprompt
            }
            return elicit_slot(session_Attributes,
                               "What table would you like access to?",
                               event['currentIntent']['slots'], "table")
        else:
            counter += 1
            session_Attributes = {
                "counter": counter,
                "validateCounter": validateCounter,
                "dateCounter": dateCounter,
                "TableString": tablestring,
                "tableReprompt": isReprompt
            }
            return elicit_slot(session_Attributes,
                               "Invalid table! Please enter a valid table!  " + "(" + str(
                                   3 - counter) + " attempt left)",
                               event['currentIntent']['slots'], "table")

    # Handle the case where the user enters 'n' or 'no'
    if event['inputTranscript'].lower() == "no" or event['inputTranscript'].lower() == 'n':
        session_Attributes['tableReprompt'] = "False"
        isReprompt = False

    # Handle the case where the user enters 'y'
    if event['inputTranscript'].lower() == "y":
        event['currentIntent']['confirmationStatus'] = "Confirmed"

    if isReprompt == "True":
        while (event['currentIntent']['confirmationStatus'] != "Denied"):
            if event['currentIntent']['confirmationStatus'] == "Confirmed":
                return elicit_slot(
                    session_Attributes,
                    "Enter the next Table",
                    event['currentIntent']['slots'], "table")

            table_name = event['currentIntent']['slotDetails']['table']['originalValue']
            tableList = [stripWhiteSpace.strip() for stripWhiteSpace in table_name.split(",")]
            for table in tableList:
                table_exist = validate_table(table)
                if type(table_exist) is dict:
                    counter = 0
                    session_Attributes['counter'] = counter
                    ButtonCheck = elicit_slot(session_Attributes, "Which one of these tables",
                                              event['currentIntent']['slots'], "table", table_exist)
                    if len(ButtonCheck['dialogAction']['responseCard']['genericAttachments'][0]['buttons']) > 5:
                        return elicit_slot(session_Attributes, "Too many options. Can you be more specific?",
                                           event['currentIntent']['slots'],
                                           "table")
                    else:
                        return ButtonCheck

                if table_exist is False:

                    if validateCounter == 2:
                        return message_handler(
                            "You have reached your attempt limit! Please try again or find a member of Team-SRE")
                    else:
                        validateCounter += 1
                        session_Attributes["validateCounter"] = validateCounter
                    return elicit_slot(
                        session_Attributes,
                        "The table(s) you have entered does not exist or you do not have access to one or more requested table(s). Enter valid table(s)! " + "(" + str(
                            3 - validateCounter) + " attempt left)",
                        event['currentIntent']['slots'], "table")

                session_Attributes['TableString'] += table + ","

                pprint(session_Attributes['TableString'])
            if event['currentIntent']['slots']['table'] and event['currentIntent']['slots']['duration'] is None:
                return reprompt(session_Attributes, "Would you like request access to more tables? (Y/N)",
                            event['currentIntent']['slots'])
            else:
                event['currentIntent']['confirmationStatus'] = "Denied"

    event['currentIntent']['confirmationStatus'] = "Denied"
    if eventDate == None:
        if dateCounter == 2:
            return message_handler("You have reached your attempt limit! Please try again or find a member of Team-SRE")
        else:
            dateCounter += 1
            session_Attributes["dateCounter"] = dateCounter
        return elicit_slot(session_Attributes, "Until when would you like access for(YYYY-MM-DD)? " + "(" + str(
            3 - dateCounter) + " attempt left)",
                           event['currentIntent']['slots'],
                           "duration")
    # get table name that the user requested

    # get today's date
    today = date.today()
    today = datetime(
        year=today.year,
        month=today.month,
        day=today.day,
    )
    # parse the date that user requested
    eventDate = parse(event['currentIntent']['slots']['duration'])
    policyLength = eventDate - today
    policyLength = int(policyLength.days)
    eventDate = str(eventDate.year).zfill(4) + '-' + str(eventDate.month).zfill(2) + '-' + str(eventDate.day).zfill(2)
    # Validate the date to see if it less than 7 days from the current date
    if policyLength < 0:
        return message_handler(
            "The date you have entered is in the past.(YYYY-MM-DD) and the date must be today's date or greater.")
    elif policyLength >= 7:
        return message_handler(
            "The number of days you have requested is greater than 7 days! I can only give you access to tables for 7 days.")
    else:
        # get user from slack
        user = getSlackMember(slack_client, userId)
        client = boto3.client('dynamodb')
        row = client.get_item(
            TableName=os.environ['dynamoDBTable'],
            Key={'key': {'S': 'blacklist_user'}})
        if 'Item' in row:
            data = row['Item']['data']['S']
            if user in data:
                return message_handler("You do not have permission to request access to these tables!")

        if user != None:
            tableList = session_Attributes["TableString"].split(",")[:-1]
            pprint(tableList)
            tables = '\n'.join(tableList)
            # using userID check if they are part of AWS and get their team
            # group can be a team if they are part of a team or user if they're not part of a team. if neither then it false
            group = getGroupIdentity(iam, user)

            if group != None:
                allowed_groups = os.environ['GroupName'].split(",")
                # if not part of a team then access has been denied
                if group.lower() not in [ag.lower() for ag in allowed_groups]:
                    return denyAccess(iam, tableList, eventDate, group, userId)

                # create the policy or get the policy if it already exists
                created, policy, existingTable = create_policy(iam, tableList, eventDate, group, True)

                if created:
                    # New policy created - need to attach it
                    is_attached = attach_policy(iam, policy, group)
                    if not is_attached:
                        # error handle if the policy is not attached
                        return message_handler("Policy could not be attached!")

                # when policy is attached, send message to the team channel as well to Team_SRE
                tables = tables.split("\n")
                existingTable = existingTable.split('\n')
                allTables=set(tables)| set(existingTable)
                tables = "\n".join(allTables)
                messageToSlack(tables, group, userId, eventDate)
                return_msg = 'READ Access has been granted to %s for the following table%s until EOD %s:\n%s' % \
                             (group, ('s' if len(tableList) > 1 else ''), eventDate, tables)
                # send message via Lex Bot
                return message_handler(return_msg)
            else:
                message_handler("You are not part of a team")
        else:
            message_handler("User Not Found")
