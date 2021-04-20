#! python3
import boto3
import time

from pprint import pprint

def updateSlot(lex, updatedSlotVersion):
    bot = lex.get_bot(
        name='Scotty',
        versionOrAlias="$LATEST"
    )

    intentVersion = []
    for intent in bot['intents']:
        updated_intent = {'intentName': intent['intentName'], 'intentVersion': intent['intentVersion']}
        newIntent = lex.get_intent(name=intent['intentName'], version="$LATEST")
        for slot in newIntent['slots']:
            if slot['name'] == "table":
                slot['slotTypeVersion'] = updatedSlotVersion
                putIntent(lex, newIntent)
                version = publishIntent(lex, newIntent)
                updated_intent['intentVersion'] = version
                break
        intentVersion.append(updated_intent)

    checksum = putbot(lex, bot, intentVersion)
    return publishbot(lex, bot, checksum)


def putIntent(lex, intents):

    lex.put_intent(
        name=intents['name'],
        description=intents['description'],
        slots=intents['slots'],
        sampleUtterances=intents['sampleUtterances'],
        dialogCodeHook=intents['dialogCodeHook'],
        fulfillmentActivity=intents['fulfillmentActivity'],
        checksum=intents['checksum']
    )



def publishIntent(lex, intent):

    newIntent = lex.get_intent(
        name=intent['name'],
        version="$LATEST"
    )

    response = lex.create_intent_version(
        name=intent['name'],
        checksum=newIntent.get('checksum')
    )
    return response['version']


def putbot(lex, bot, intent):

    response = lex.put_bot(
        name=bot['name'],
        description=bot['description'],
        intents=intent,
        clarificationPrompt=bot['clarificationPrompt'],
        abortStatement=bot['abortStatement'],
        idleSessionTTLInSeconds=60,
        voiceId="Ivy",
        processBehavior="BUILD",
        locale="en-US",
        childDirected=False,
        checksum=bot.get("checksum")
    )
    bot_status = response.get('status')
    checksum = response.get('checksum')
    # Wait for BOT status to be READY
    while 'READY' not in bot_status:
        bot = lex.get_bot(
            name=bot['name'],
            versionOrAlias='$LATEST'
        )
        bot_status = bot.get('status')
        checksum = bot.get('checksum')
        print('   Not ready yet...')
        time.sleep(5)
    return checksum


def publishbot(lex, bot, checksum):

    print('Publishing new Bot Version')
    result = False
    response = lex.create_bot_version(name=bot['name'], checksum=checksum)
    if 'ResponseMetadata' in response and response['ResponseMetadata']['HTTPStatusCode'] == 201:
        result = True
    return result

def reactToDynamoDB():

    client = boto3.client("dynamodb")
    paginator = client.get_paginator('list_tables')
    # get all the list of table in the current environment
    pages = paginator.paginate()
    tablePages = []
    for page in pages:
        tablePages.append(page['TableNames'])

    tablelist = []
    # Creating a existing table
    for List in tablePages:
        for table in List:
            tablelist.append(table)
    # coverting the list to set
    set_table_name = set(tablelist)
    # pprint(set_table_name)
    lex = boto3.client('lex-models')
    # Getting the current slot Type for tables
    current_slot = lex.get_slot_type(
        name="table",
        version="$LATEST"
    )

    #  creating a set of existing table in the slot type
    table_in_slot = set(current_slot['enumerationValues'][0]['synonyms'])

    tableRemoved = len(table_in_slot - set_table_name)
    tableAdded = len(set_table_name - table_in_slot)


    # if the number of changes in a table is greater than 0: update the current list in slot type
    if tableRemoved is not 0 or tableAdded is not 0:
        response = lex.put_slot_type(
            name="table",
            description="tables in dynamodb",
            enumerationValues=[
                {
                    "value": "table",
                    "synonyms": tablelist
                }
            ],
            valueSelectionStrategy='TOP_RESOLUTION',
            checksum=current_slot.get('checksum')
        )

        slot = lex.get_slot_type(
            name="table",
            version="$LATEST"
        )
        updatedSlotVersion = lex.create_slot_type_version(
            name="table",
            checksum=slot.get('checksum')
        )['version']

        if updateSlot(lex, updatedSlotVersion):
            print("Table List has been updated!")
        else:
            print("The bot couldnt be updated!")
    else:
        print("No change were made to the slots")



# Updating the existing slot if the any changes has occured in Dynamo DB
def lambda_handler(event, context):  # event, context


    if event['detail']['eventName'] in ['CreateTable','DeleteTable']:
        reactToDynamoDB()
    else:
        print('No updates!')

if __name__ == "__main__":
    reactToDynamoDB()
