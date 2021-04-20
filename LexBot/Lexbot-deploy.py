import boto3
import argparse
import json
import time
import os
import botocore.errorfactory


def _bot_exists(lex_client, bot_name):
    return_value = False
    bots_list = []
    response = lex_client.get_bots(nameContains=bot_name)
    if 'bots' in response:
        bots_list.extend(response['bots'])
    while 'nextToken' in response:
        response = lex_client.get_bots(nameContains=bot_name, nextToken=response['nextToken'])
        if 'slotTypes' in response:
            bots_list.extend(response['bots'])
    for bot in bots_list:
        if bot['name'] == bot_name:
            return_value = True
            break
    return return_value


def _slot_exists(lex_client, slot_name):
    return_value = False
    slots_list = []
    response = lex_client.get_slot_types(nameContains=slot_name)
    if 'slotTypes' in response:
        slots_list.extend(response['slotTypes'])
    while 'nextToken' in response:
        response = lex_client.get_slot_types(nameContains=slot_name, nextToken=response['nextToken'])
        if 'slotTypes' in response:
            slots_list.extend(response['slotTypes'])
    for slot in slots_list:
        if slot['name'] == slot_name:
            return_value = True
            break
    return return_value


def putSlot(client, slot_name, slot_description, slot_values):
    result = False
    if not _slot_exists(client, slot_name):
        print('   Creating slot type %s' % slot_name)
        if slot_values[0]["value"] == "None":
            print('      No slot values defined - returning')
            return result
        response = client.put_slot_type(
            name=slot_name,
            description=slot_description,
            enumerationValues=slot_values,
            valueSelectionStrategy="TOP_RESOLUTION"
        )
        # print(str(response))
        if 'ResponseMetadata' in response:
            if response['ResponseMetadata']['HTTPStatusCode'] == 200 or response['ResponseMetadata']['HTTPStatusCode'] == 201:
                result = True
    else:
        # Slot already exists
        result = True
    return result


def createSlotTypeVersion(client, slot_name):
    slot_version = None
    get_slot_type_response = client.get_slot_type(
        name=slot_name,
        version="$LATEST"
    )
    create_slot_type_version_response = client.create_slot_type_version(
        name=slot_name,
        checksum= get_slot_type_response.get('checksum')
    )
    # Need the VERSION from the response
    slot_version = create_slot_type_version_response['version']
    print("%s has version %s" % (slot_name, slot_version))
    return slot_version


def addPermission(lambda_client, bot_name, intent_name, region, account_id):
    response = lambda_client.add_permission(
        Action='lambda:InvokeFunction',
        FunctionName=intent_name,
        StatementId=bot_name,
        Principal='lex.amazonaws.com',
        SourceArn='arn:aws:lex:' + region + ":" + account_id + ':intent:' + intent_name + ':*'
    )

    if 'ResponseMetadata' in response and response['ResponseMetadata']['HTTPStatusCode'] == 201:
        return True

    return False


def _intent_exists(lex_client, intent_name):
    return_value = False
    intents_list = []
    response = lex_client.get_intents(nameContains=intent_name)
    if 'intents' in response:
        intents_list.extend(response['intents'])
    while 'nextToken' in response:
        response = lex_client.get_intents(nameContains=intent_name, nextToken=response['nextToken'])
        if 'intents' in response:
            intents_list.extend(response['intents'])
    for intent in intents_list:
        if intent['name'] == intent_name:
            return_value = True
            break
    return return_value


def update_intent(lex_client, lambda_client, intent_name, slots):
    status = False
    # get lambda function
    lambda_arn = None
    response = lambda_client.get_function(FunctionName=intent_name)
    if 'ResponseMetadata' in response and response['ResponseMetadata']['HTTPStatusCode'] == 200:
        lambda_arn = response['Configuration']['FunctionArn']

    slot_list = []
    intent_def = None
    intent_def_file = 'intents/%s.json' % intent_name
    if os.path.exists(intent_def_file):
        with open(intent_def_file, 'r') as f:
            intent_def = json.loads(f.read())
        # create slot list with actual definitions instead of just names
        for slot in intent_def['slots']:
            # Get the version
            slot_definition = slots[slot]['slot_definition']
            # Modify the version - if it exists
            if 'slotTypeVersion' in slot:
                slot_definition['slotTypeVersion'] = slots[slot]['slot_version']
            slot_list.append(slot_definition)

    if lambda_arn:
        dialog_code_hook = {
            'uri': lambda_arn,
            'messageVersion': '1.0'
        }
        if _intent_exists(lex_client, intent_name):
            # get the existing intent
            get_intent_response = lex_client.get_intent(name=intent_name, version="$LATEST")
            if 'ResponseMetadata' in get_intent_response and get_intent_response['ResponseMetadata']['HTTPStatusCode'] == 200:
                checksum = get_intent_response['checksum']
                # put-intent
                put_intent_response = lex_client.put_intent(
                    name=intent_name,
                    description=intent_def['description'],
                    slots=slot_list,
                    sampleUtterances=intent_def['sampleUtterances'],
                    dialogCodeHook=dialog_code_hook,
                    fulfillmentActivity=intent_def['fulfillmentActivity'],
                    checksum=checksum
                )
                if 'ResponseMetadata' in put_intent_response and put_intent_response['ResponseMetadata']['HTTPStatusCode'] == 200:
                    status = True
        else:
            # create new intent
            put_intent_response = lex_client.put_intent(
                name=intent_name,
                description=intent_def['description'],
                slots=slot_list,
                sampleUtterances=intent_def['sampleUtterances'],
                dialogCodeHook=dialog_code_hook,
                fulfillmentActivity=intent_def['fulfillmentActivity']
            )
            if 'ResponseMetadata' in put_intent_response and put_intent_response['ResponseMetadata']['HTTPStatusCode'] == 200:
                status = True
    return status


def createIntentVersion(client, intent_name):
    get_intent_response = client.get_intent(name=intent_name,version="$LATEST")

    create_intent_version_response = client.create_intent_version(
        name=intent_name,
        checksum=get_intent_response.get('checksum')
    )

    # Need the VERSION from the response
    return create_intent_version_response['version']


def initializeBot(client, botName):
    print('Creating Bot')
    client.put_bot(
        name=botName,
        description="Scotty Bot",
        clarificationPrompt={
            'messages': [
                {
                    "contentType": "PlainText",
                    "content": "Sorry, can you please repeat that?"
                }
            ],
            "maxAttempts": 2
        },
        abortStatement={
            "messages": [
                {
                    "contentType": "PlainText",
                    "content": "Sorry, I could not understand. Goodbye"
                }
            ]
        },
        idleSessionTTLInSeconds=60,
        voiceId="Ivy",
        locale="en-US",
        childDirected=False
    )
    # Wait 5 seconds before continuing
    time.sleep(5)


def buildBot(client, botName, intents):
    print('Building new Bot version')
    bot = client.get_bot(
        name=botName,
        versionOrAlias='$LATEST'
    )
    checksum = bot.get("checksum")

    response = client.put_bot(
        name=botName,
        description="Scotty bot",
        intents=intents,
        clarificationPrompt={
            'messages': [
                {
                    "contentType": "PlainText",
                    "content": "Sorry, can you please repeat that?"
                }
            ],
            "maxAttempts": 2
        },
        abortStatement={
            "messages": [
                {
                    "contentType": "PlainText",
                    "content": "Sorry, I could not understand. Goodbye"
                }
            ]
        },
        idleSessionTTLInSeconds=60,
        voiceId="Ivy",
        processBehavior="BUILD",
        locale="en-US",
        childDirected=False,
        checksum=checksum
    )

    bot_status = response.get('status')
    checksum = response.get('checksum')
    # Wait for BOT status to be READY
    while 'READY' not in bot_status:
        bot = client.get_bot(
            name=botName,
            versionOrAlias='$LATEST'
        )
        bot_status = bot.get('status')
        checksum = bot.get('checksum')
        print('   Not ready yet...')
        time.sleep(5)
    return checksum


def publishBot(client, botName, checksum):
    print('Publishing new Bot Version')
    result = False
    response = client.create_bot_version(name=botName, checksum=checksum)
    if 'ResponseMetadata' in response and response['ResponseMetadata']['HTTPStatusCode'] == 201:
        result = True
    return result


def _alias_exists(lex_client, bot_name, bot_alias):
    return_value = False
    aliases_list = []
    response = lex_client.get_bot_aliases(botName=bot_name, nameContains=bot_alias)
    if 'BotAliases' in response:
        aliases_list.extend(response['BotAliases'])
    while 'nextToken' in response:
        response = lex_client.get_bot_aliases(botName=bot_name, nameContains=bot_alias, nextToken=response['nextToken'])
        if 'BotAliases' in response:
            aliases_list.extend(response['BotAliases'])
    for alias in aliases_list:
        if alias['name'] == bot_alias:
            return_value = True
            break
    return return_value


def createBotAlias(client, bot_name, bot_alias='Prod'):
    checksum = None
    if _alias_exists(client, bot_name, bot_alias):
        response = client.get_bot_alias(
            name=bot_alias,
            botName=bot_name
        )
        checksum = response.get('checksum')
    response = None
    if checksum:
        response = client.put_bot_alias(
            name=bot_alias,
            description="version 1",
            botVersion="$LATEST",
            botName=bot_name,
            checksum=checksum
        )
    else:
        response = client.put_bot_alias(
            name=bot_alias,
            description="version 1",
            botVersion="$LATEST",
            botName=bot_name
        )
    if 'ResponseMetadata' in response and response['ResponseMetadata']['HTTPStatusCode'] == 200:
        if checksum:
            print('Updated Bot alias (%s)' % bot_alias)
        else:
            print('Created new Bot alias (%s)' % bot_alias)


def new_bot_message():
    print('\n\n*********** IMPORTANT ***********\n\n')
    print('New Bot created - you MUST visit the LEX console and perform the following steps:')
    print(' - click on each of the intents and grant permission for the associated lambda function')
    print(' - under the Channels tab, select Slack and fill in the following:')
    print('   - Channel Name')
    print('   - Alias (select Prod from dropdown)')
    print('   - Client Id (from Slack App)')
    print('   - Client Secret (from Slack App)')
    print('   - Verification Token (from Slack App)')
    print(' - after activating, you will need the following to enter in the Slack App config:')
    print('   - Postback URL')
    print('   - OAuth URL')
    print(' - finish the Slack app configuration, using the two URLs mentioned above')
    print(' - add the app to your slack workspace')
    print('\n')
    print('See README in this repo for more information')


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='value for ScottyScotty Bot')
    parser.add_argument("--name", help="The name for the Lex Bot", dest='name', required=True)
    parser.add_argument("--profile", help="The AWS profile to use", dest="profile", default=None, required=False)
    parser.add_argument("--region", help="The locale for the Lex", dest="region", required=True)

    args = parser.parse_args()

    intents = []
    slots = []

    session = boto3.session.Session(profile_name=args.profile, region_name=args.region)
    lex_client = session.client("lex-models")
    sts_client = session.client("sts")
    lambda_client = session.client("lambda")
    account_id = sts_client.get_caller_identity()['Account']

    new_bot = False
    if not _bot_exists(lex_client, args.name):
        new_bot = True

    with open ('slots.json', 'r') as slot_file:
        slots = json.loads(slot_file.read())

    # create / update the slots
    print('Creating/Updating slots for %s' % args.name)
    for slot in slots:
        slot_definition = slots[slot]['slot_definition']['description']
        slot_values = slots[slot]['slot_enumeration_values']
        if putSlot(lex_client, slot, slot_definition, slot_values):
            slot_version = createSlotTypeVersion(lex_client, slot)
            slots[slot]['slot_version'] = slot_version

    # Create / update the intents
    intent_files = os.listdir('intents')
    for filename in intent_files:
        intent_name = filename.split('.json')[0]
        print('Creating/Updating %s intent' % intent_name)
        if new_bot or not _intent_exists(lex_client, intent_name):
            addPermission(lambda_client, args.name, intent_name, args.region, account_id)
        if update_intent(lex_client, lambda_client, intent_name, slots):
            intent_version = createIntentVersion(lex_client, intent_name)
            intents.append({'intentName': intent_name, 'intentVersion': intent_version})

    if new_bot:
        initializeBot(lex_client, args.name)

    checksum = buildBot(lex_client, args.name, intents)
    if publishBot(lex_client, args.name, checksum):
        createBotAlias(lex_client, args.name)
    else:
        print('Error publishing %s' % args.name)

    if new_bot:
        new_bot_message()
