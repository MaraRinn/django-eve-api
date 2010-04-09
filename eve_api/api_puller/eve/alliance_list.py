"""
This module pulls the master alliance XML list from the API and dumps it in the
api_puller/xml_cache directory as needed. All alliance data must be updated
in bulk, which is done reasonably quickly.
"""
from xml.dom import minidom
from datetime import datetime
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from eve_proxy.models import CachedDocument
from eve_proxy.proxy_exceptions import InvalidAPIResponseException

# This stores a list of all corps whose alliance attribute has been updated.
UPDATED_CORPS = []

def __get_model_class(class_name):
    """
    Shortcut method for returning models. This is done to avoid circular
    dependencies.
    """
    return ContentType.objects.get(app_label="eve_api", 
                                   model=class_name).model_class()

def __update_corp_from_alliance_node(alliance_node, alliance):
    """
    Updates a corp's alliance membership from an alliance <row> element.
    """
    member_corp_nodelist = alliance_node.getElementsByTagName('rowset')[0].childNodes

    for node in member_corp_nodelist:
        corp_row_node = None
        try:
            # If this fails, this is a Text node and should be ignored.
            corporation_id = int(node.getAttribute('corporationID'))
        except AttributeError:
            # This is probably a Text node, ignore it.
            continue
        
        ApiPlayerCorporation = __get_model_class('apiplayercorporation')
        corp, created = ApiPlayerCorporation.objects.get_or_create(id=corporation_id)
        corp.id = corporation_id
        corp.alliance = alliance
        corp.alliance_join_date = datetime.strptime(alliance_node.getAttribute('startDate'),
                                                  '%Y-%m-%d %H:%M:%S')
        corp.save()
        # Store the corp in the updated corps list for later checks.
        UPDATED_CORPS.append(corp.id)
        
def __remove_invalid_corp_alliance_memberships():
    """
    Compares UPDATED_CORPS list to the full list of player corporations. If
    the corporation was not updated from being found in one of the alliance
    data sets, it has no alliance affiliation and needs to be set to no
    alliance if it is not already a None value.
    """
    ApiPlayerCorporation = __get_model_class('apiplayercorporation')
    all_corps = ApiPlayerCorporation.objects.all()
    # This is not terribly efficient, but it will do for a background process.
    for corp in all_corps:
        """
        If the corp is not in the UPDATED_CORP list that was built from
        alliance memberCorporations rowsets, then it does not belong to an
        alliance and should be un-allianced if it currently is.
        """
        if corp.id not in UPDATED_CORPS and corp.alliance != None:
            corp.alliance = None
            corp.save()

def query_alliance_list(**kwargs):
    """
    This method runs a full import of all known alliances. This may take a few
    minutes and should be ran regularly if you are maintaining a full corp
    list of all EVE corps as well.
    """
    print "Querying /eve/AllianceList.xml.aspx/"
    alliance_doc = CachedDocument.objects.api_query('/eve/AllianceList.xml.aspx',
                                                    **kwargs)
    print "Parsing..."
    dom = minidom.parseString(alliance_doc.body)
    result_node_children = dom.getElementsByTagName('result')[0].childNodes
    
    # This will hold a reference to the <rowset name="alliances> Element.
    alliances_rowset_node = None
    # For some odd reason, two text nodes and an Element are children of
    # the result Element. Find the alliances rowset from its children.
    for node in result_node_children:
        try:
            # The node we want has a 'name' attribute.
            if node.getAttribute('name') == 'alliances':
                # Store the reference for later use.
                alliances_rowset_node = node
                # Look no further.
                break
        except AttributeError:
            # This must be a Text node, ignore it.
            continue
        
    if alliances_rowset_node == None:
        # No alliance rowset node could be found. CCP server problems.
        raise InvalidAPIResponseException(alliance_doc.body)
    
    # We now have a list of <row> tags representing each alliance.
    print "Updating alliance and member corporation data..."
    for alliance_node in alliances_rowset_node.childNodes:
        try:
            # If this fails, this is a Text node and should be ignored.
            alliance_id = int(alliance_node.getAttribute('allianceID'))
        except AttributeError:
            # This is probably a Text node, ignore it.
            continue
        
        """
        Search for an existing ApiPlayerAlliance object with the given
        alliance ID. Create one if it doesn't exist, retrieve the existing
        object if it's already there.
        """
        ApiPlayerAlliance = __get_model_class('apiplayeralliance')
        alliance, created = ApiPlayerAlliance.objects.get_or_create(id=alliance_id)
        alliance.id = alliance_id
        alliance.name = alliance_node.getAttribute('name')
        alliance.ticker = alliance_node.getAttribute('shortName')
        alliance.member_count = alliance_node.getAttribute('memberCount')
        alliance.date_founded = datetime.strptime(alliance_node.getAttribute('startDate'),
                                                  '%Y-%m-%d %H:%M:%S')
        alliance.save()
        # Update member corp alliance attributes.
        __update_corp_from_alliance_node(alliance_node, alliance)
    
    print "Alliances and member corps updated."
    print "Removing corps alliance memberships that are no longer valid..."
    __remove_invalid_corp_alliance_memberships()
