# This python autopsy module will export the Amcache Regiatry Hive and then call
# the command line version of the Export_Amcache program.  A sqlite database that
# contains the Amcache information is created then imported into the extracted
# view section of Autopsy.
#
# Contact: Mark McKinnon [Mark [dot] McKinnon <at> Davenport [dot] edu]
#
# This is free and unencumbered software released into the public domain.
#
# Anyone is free to copy, modify, publish, use, compile, sell, or
# distribute this software, either in source code form or as a compiled
# binary, for any purpose, commercial or non-commercial, and by any
# means.
#
# In jurisdictions that recognize copyright laws, the author or authors
# of this software dedicate any and all copyright interest in the
# software to the public domain. We make this dedication for the benefit
# of the public at large and to the detriment of our heirs and
# successors. We intend this dedication to be an overt act of
# relinquishment in perpetuity of all present and future rights to this
# software under copyright law.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR
# OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
# ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.

# Amcache module to parse the amcache registry hive.
# June 2016
# 
# Comments 
#   Version 1.0 - Initial version - June 2016
#   Version 1.1 - Added custom artifacts and attributes - Aug 31, 2016
#   version 1.2 - Added Linux Support
#   Version 1.3 - fix options panel - March 2018
# 

import jarray
import inspect
import os
import subprocess

from javax.swing import JCheckBox
from javax.swing import JList
from javax.swing import JTextArea
from javax.swing import BoxLayout
from java.awt import GridLayout
from java.awt import BorderLayout
from javax.swing import BorderFactory
from javax.swing import JToolBar
from javax.swing import JPanel
from javax.swing import JFrame
from javax.swing import JScrollPane
from javax.swing import JComponent
from java.awt.event import KeyListener


from java.lang import Class
from java.lang import System
from java.sql  import DriverManager, SQLException
from java.util.logging import Level
from java.io import File
from org.sleuthkit.datamodel import SleuthkitCase
from org.sleuthkit.datamodel import AbstractFile
from org.sleuthkit.datamodel import ReadContentInputStream
from org.sleuthkit.datamodel import BlackboardArtifact
from org.sleuthkit.datamodel import BlackboardAttribute
from org.sleuthkit.autopsy.ingest import IngestModule
from org.sleuthkit.autopsy.ingest.IngestModule import IngestModuleException
from org.sleuthkit.autopsy.ingest import DataSourceIngestModule
from org.sleuthkit.autopsy.ingest import IngestModuleFactoryAdapter
from org.sleuthkit.autopsy.ingest import GenericIngestModuleJobSettings
from org.sleuthkit.autopsy.ingest import IngestModuleIngestJobSettingsPanel
from org.sleuthkit.autopsy.ingest import IngestMessage
from org.sleuthkit.autopsy.ingest import IngestServices
from org.sleuthkit.autopsy.ingest import ModuleDataEvent
from org.sleuthkit.autopsy.coreutils import Logger
from org.sleuthkit.autopsy.coreutils import PlatformUtil
from org.sleuthkit.autopsy.casemodule import Case
from org.sleuthkit.autopsy.casemodule.services import Services
from org.sleuthkit.autopsy.casemodule.services import FileManager
from org.sleuthkit.autopsy.datamodel import ContentUtils


# Factory that defines the name and details of the module and allows Autopsy
# to create instances of the modules that will do the analysis.
class ParseAmcacheIngestModuleFactory(IngestModuleFactoryAdapter):

    def __init__(self):
        self.settings = None

    moduleName = "Parse Amcache"
    
    def getModuleDisplayName(self):
        return self.moduleName
    
    def getModuleDescription(self):
        return "Parses Amcache"
    
    def getModuleVersionNumber(self):
        return "1.3"

    def getDefaultIngestJobSettings(self):
        return GenericIngestModuleJobSettings()


    def hasIngestJobSettingsPanel(self):
        return True

    # TODO: Update class names to ones that you create below
    def getIngestJobSettingsPanel(self, settings):
        if not isinstance(settings, GenericIngestModuleJobSettings):
            raise IllegalArgumentException("Expected settings argument to be instanceof GenericIngestModuleSettings")
        self.settings = settings
        return Process_AmcacheWithUISettingsPanel(self.settings)    
    
    def isDataSourceIngestModuleFactory(self):
        return True

    def createDataSourceIngestModule(self, ingestOptions):
        return ParseAmcacheIngestModule(self.settings)

# Data Source-level ingest module.  One gets created per data source.
class ParseAmcacheIngestModule(DataSourceIngestModule):

    _logger = Logger.getLogger(ParseAmcacheIngestModuleFactory.moduleName)

    def log(self, level, msg):
        self._logger.logp(level, self.__class__.__name__, inspect.stack()[1][3], msg)

    def __init__(self, settings):
        self.context = None
        self.local_settings = settings
        self.List_Of_tables = []

    # Where any setup and configuration is done
    # 'context' is an instance of org.sleuthkit.autopsy.ingest.IngestJobContext.
    # See: http://sleuthkit.org/autopsy/docs/api-docs/3.1/classorg_1_1sleuthkit_1_1autopsy_1_1ingest_1_1_ingest_job_context.html
    def startUp(self, context):
        self.context = context

        # Get path to EXE based on where this script is run from.
        # Assumes EXE is in same folder as script
        # Verify it is there before any ingest starts
        if PlatformUtil.isWindowsOS():
            self.path_to_exe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "amcache_parser.exe")
            if not os.path.exists(self.path_to_exe):
                raise IngestModuleException("Windows Executable was not found in module folder")
        elif PlatformUtil.getOSName() == 'Linux':
            self.path_to_exe = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'amcache_parser')
            if not os.path.exists(self.path_to_exe):
                raise IngestModuleException("Linux Executable was not found in module folder")

        if self.local_settings.getSetting('associateFileEntries') =='true':
            self.List_Of_tables.append('associated_file_entries')
        if self.local_settings.getSetting('programEntries') == 'true':
            self.List_Of_tables.append('program_entries')
        if self.local_settings.getSetting('unassociatePrograms') == 'true':
            self.List_Of_tables.append('unassociated_programs')
        
        #self.logger.logp(Level.INFO, Process_EVTX1WithUI.__name__, "startUp", str(self.List_Of_Events))
        self.log(Level.INFO, str(self.List_Of_tables) + " >> " + str(len(self.List_Of_tables)))

        
        # Throw an IngestModule.IngestModuleException exception if there was a problem setting up
        # raise IngestModuleException(IngestModule(), "Oh No!")
        pass

    # Where the analysis is done.
    # The 'dataSource' object being passed in is of type org.sleuthkit.datamodel.Content.
    # See: http://www.sleuthkit.org/sleuthkit/docs/jni-docs/interfaceorg_1_1sleuthkit_1_1datamodel_1_1_content.html
    # 'progressBar' is of type org.sleuthkit.autopsy.ingest.DataSourceIngestModuleProgress
    # See: http://sleuthkit.org/autopsy/docs/api-docs/3.1/classorg_1_1sleuthkit_1_1autopsy_1_1ingest_1_1_data_source_ingest_module_progress.html
    def process(self, dataSource, progressBar):

        if len(self.List_Of_tables) < 1:
            message = IngestMessage.createMessage(IngestMessage.MessageType.DATA, "ParseAmcache", " No Amcache tables Selected to Parse " )
            IngestServices.getInstance().postMessage(message)
            return IngestModule.ProcessResult.ERROR

        # we don't know how much work there is yet
        progressBar.switchToIndeterminate()
        
       # Set the database to be read to the once created by the prefetch parser program
        skCase = Case.getCurrentCase().getSleuthkitCase();
        fileManager = Case.getCurrentCase().getServices().getFileManager()
        files = fileManager.findFiles(dataSource, "Amcache.hve")
        numFiles = len(files)
        self.log(Level.INFO, "found " + str(numFiles) + " files")
        progressBar.switchToDeterminate(numFiles)
        fileCount = 0;

		# Create Event Log directory in temp directory, if it exists then continue on processing		
        Temp_Dir = Case.getCurrentCase().getTempDirectory()
        temp_dir = os.path.join(Temp_Dir, "amcache")
        self.log(Level.INFO, "create Directory " + temp_dir)
        try:
		    os.mkdir(temp_dir)
        except:
		    self.log(Level.INFO, "Amcache Directory already exists " + temp_dir)
			
        # Write out each Event Log file to the temp directory
        for file in files:
            
            # Check if the user pressed cancel while we were busy
            if self.context.isJobCancelled():
                return IngestModule.ProcessResult.OK

            #self.log(Level.INFO, "Processing file: " + file.getName())
            fileCount += 1

            # Save the DB locally in the temp folder. use file id as name to reduce collisions
            lclDbPath = os.path.join(temp_dir, file.getName())
            ContentUtils.writeToFile(file, File(lclDbPath))
                        

        # Example has only a Windows EXE, so bail if we aren't on Windows
        # Run the EXE, saving output to a sqlite database
        self.log(Level.INFO, "Running program on data source parm 1 ==> " + Temp_Dir + "\Amcache\Amcache.hve  Parm 2 ==> " + Temp_Dir + "\Amcache.db3")
        subprocess.Popen([self.path_to_exe, os.path.join(temp_dir, "Amcache.hve"), os.path.join(temp_dir, "Amcache.db3")]).communicate()[0]   
               
        for file in files:	
           # Open the DB using JDBC
           lclDbPath = os.path.join(temp_dir, "Amcache.db3")
           self.log(Level.INFO, "Path the Amcache database file created ==> " + lclDbPath)
           try: 
               Class.forName("org.sqlite.JDBC").newInstance()
               dbConn = DriverManager.getConnection("jdbc:sqlite:%s"  % lclDbPath)
           except SQLException as e:
               self.log(Level.INFO, "Could not open database file (not SQLite) " + file.getName() + " (" + e.getMessage() + ")")
               return IngestModule.ProcessResult.OK
            
           # Query the contacts table in the database and get all columns.
           for am_table_name in self.List_Of_tables:           
               try:
                   stmt = dbConn.createStatement()
                   resultSet = stmt.executeQuery("Select tbl_name from SQLITE_MASTER where lower(tbl_name) in ('" + am_table_name + "'); ")
                   # resultSet = stmt.executeQuery("Select tbl_name from SQLITE_MASTER where lower(tbl_name) in ('associated_file_entries', " + \
                                                 # "'unassociated_programs', 'program_entries'); ")
                   self.log(Level.INFO, "query SQLite Master table for " + am_table_name)
               except SQLException as e:
                   self.log(Level.INFO, "Error querying database for Prefetch table (" + e.getMessage() + ")")
                   return IngestModule.ProcessResult.OK

               # Cycle through each row and create artifacts
               while resultSet.next():
                   try: 
                       self.log(Level.INFO, "Result (" + resultSet.getString("tbl_name") + ")")
                       table_name = resultSet.getString("tbl_name")
                       #self.log(Level.INFO, "Result get information from table " + resultSet.getString("tbl_name") + " ")
                       SQL_String_1 = "Select * from " + table_name + ";"
                       SQL_String_2 = "PRAGMA table_info('" + table_name + "')"
                       artifact_name = "TSK_" + table_name.upper()
                       artifact_desc = "Amcache " + table_name.upper()
                       #self.log(Level.INFO, SQL_String_1)
                       #self.log(Level.INFO, "Artifact_Name ==> " + artifact_name)
                       #self.log(Level.INFO, "Artifact_desc ==> " + artifact_desc)
                       #self.log(Level.INFO, SQL_String_2)
                       try:
                            self.log(Level.INFO, "Begin Create New Artifacts")
                            artID_amc = skCase.addArtifactType( artifact_name, artifact_desc)
                       except:		
                            self.log(Level.INFO, "Artifacts Creation Error, some artifacts may not exist now. ==> ")

                       artID_amc = skCase.getArtifactTypeID(artifact_name)
                       artID_amc_evt = skCase.getArtifactType(artifact_name)
                       
                       Column_Names = []
                       Column_Types = []
                       resultSet2  = stmt.executeQuery(SQL_String_2)
                       while resultSet2.next(): 
                          Column_Names.append(resultSet2.getString("name").upper())
                          Column_Types.append(resultSet2.getString("type").upper())
                          #self.log(Level.INFO, "Add Attribute TSK_" + resultSet2.getString("name").upper() + " ==> " + resultSet2.getString("type"))
                          #self.log(Level.INFO, "Add Attribute TSK_" + resultSet2.getString("name").upper() + " ==> " + resultSet2.getString("name"))
                          #attID_ex1 = skCase.addAttrType("TSK_" + resultSet2.getString("name").upper(), resultSet2.getString("name"))
                          #self.log(Level.INFO, "attribure id for " + "TSK_" + resultSet2.getString("name") + " == " + str(attID_ex1))
                          if resultSet2.getString("type").upper() == "TEXT":
                              try:
                                  attID_ex1 = skCase.addArtifactAttributeType("TSK_" + resultSet2.getString("name").upper(), BlackboardAttribute.TSK_BLACKBOARD_ATTRIBUTE_VALUE_TYPE.STRING, resultSet2.getString("name"))
                                  #self.log(Level.INFO, "attribure id for " + "TSK_" + resultSet2.getString("name") + " == " + str(attID_ex1))
                              except:		
                                  self.log(Level.INFO, "Attributes Creation Error, " + resultSet2.getString("name") + " ==> ")
                          elif resultSet2.getString("type").upper() == "":
                              try:
                                  attID_ex1 = skCase.addArtifactAttributeType("TSK_" + resultSet2.getString("name").upper(), BlackboardAttribute.TSK_BLACKBOARD_ATTRIBUTE_VALUE_TYPE.STRING, resultSet2.getString("name"))
                                  #self.log(Level.INFO, "attribure id for " + "TSK_" + resultSet2.getString("name") + " == " + str(attID_ex1))
                              except:		
                                  self.log(Level.INFO, "Attributes Creation Error, " + resultSet2.getString("name") + " ==> ")
                          else:
                              try:
                                  attID_ex1 = skCase.addArtifactAttributeType("TSK_" + resultSet2.getString("name").upper(), BlackboardAttribute.TSK_BLACKBOARD_ATTRIBUTE_VALUE_TYPE.LONG, resultSet2.getString("name"))
                                  #self.log(Level.INFO, "attribure id for " + "TSK_" + resultSet2.getString("name") + " == " + str(attID_ex1))
                              except:		
                                  self.log(Level.INFO, "Attributes Creation Error, " + resultSet2.getString("name") + " ==> ")

                                             
                       resultSet3 = stmt.executeQuery(SQL_String_1)
                       while resultSet3.next():
                          art = file.newArtifact(artID_amc)
                          Column_Number = 1
                          for col_name in Column_Names:
                             #self.log(Level.INFO, "Result get information for column " + Column_Names[Column_Number - 1] + " ")
                             #self.log(Level.INFO, "Result get information for column_number " + str(Column_Number) + " ")
                             #self.log(Level.INFO, "Result get information for column type " + Column_Types[Column_Number - 1] + " <== ")
                             c_name = "TSK_" + col_name
                             #self.log(Level.INFO, "Attribute Name is " + c_name + " ")
                             attID_ex1 = skCase.getAttributeType(c_name)
                             if Column_Types[Column_Number - 1] == "TEXT":
                                 art.addAttribute(BlackboardAttribute(attID_ex1, ParseAmcacheIngestModuleFactory.moduleName, resultSet3.getString(Column_Number)))
#                                 art.addAttribute(BlackboardAttribute(attID_ex1, ParseAmcacheIngestModuleFactory.moduleName, resultSet3.getString(Column_Number)))
                             elif Column_Types[Column_Number - 1] == "":
                                  art.addAttribute(BlackboardAttribute(attID_ex1, ParseAmcacheIngestModuleFactory.moduleName, resultSet3.getString(Column_Number)))
#                             elif Column_Types[Column_Number - 1] == "BLOB":
#                                 art.addAttribute(BlackboardAttribute(attID_ex1, ParseAmcacheIngestModuleFactory.moduleName, "BLOBS Not Supported"))
#                             elif Column_Types[Column_Number - 1] == "REAL":
#                                 art.addAttribute(BlackboardAttribute(attID_ex1, ParseAmcacheIngestModuleFactory.moduleName, resultSet3.getFloat(Column_Number)))
                             else:
                                 #self.log(Level.INFO, "Value for column type ==> " + str(resultSet3.getInt(Column_Number)) + " <== ")
                                 art.addAttribute(BlackboardAttribute(attID_ex1, ParseAmcacheIngestModuleFactory.moduleName, long(resultSet3.getInt(Column_Number))))
                             Column_Number = Column_Number + 1
                       IngestServices.getInstance().fireModuleDataEvent(ModuleDataEvent(ParseAmcacheIngestModuleFactory.moduleName, artID_amc_evt, None))
                            
                   except SQLException as e:
                       self.log(Level.INFO, "Error getting values from contacts table (" + e.getMessage() + ")")

            # Clean up
               stmt.close()
           dbConn.close()
        #os.remove(lclDbPath)
        	
		#Clean up EventLog directory and files
        for file in files:
            try:
			    os.remove(Temp_Dir + "\\" + file.getName())
            except:
			    self.log(Level.INFO, "removal of Amcache file failed " + Temp_Dir + "\\" + file.getName())
        try:
             os.rmdir(Temp_Dir)		
        except:
		     self.log(Level.INFO, "removal of Amcache directory failed " + Temp_Dir)

        # After all databases, post a message to the ingest messages in box.
        message = IngestMessage.createMessage(IngestMessage.MessageType.DATA,
            "Amcache Parser", " Amcache Has Been Analyzed " )
        IngestServices.getInstance().postMessage(message)

        return IngestModule.ProcessResult.OK                
		
class Process_AmcacheWithUISettingsPanel(IngestModuleIngestJobSettingsPanel):
    # Note, we can't use a self.settings instance variable.
    # Rather, self.local_settings is used.
    # https://wiki.python.org/jython/UserGuide#javabean-properties
    # Jython Introspector generates a property - 'settings' on the basis
    # of getSettings() defined in this class. Since only getter function
    # is present, it creates a read-only 'settings' property. This auto-
    # generated read-only property overshadows the instance-variable -
    # 'settings'
    
    # We get passed in a previous version of the settings so that we can
    # prepopulate the UI
    # TODO: Update this for your UI
    def __init__(self, settings):
        self.local_settings = settings
        self.initComponents()
        self.customizeComponents()
    
    # TODO: Update this for your UI
    def checkBoxEvent(self, event):
        if self.checkbox.isSelected():
            self.local_settings.setSetting('associateFileEntries', 'true')
        else:
            self.local_settings.setSetting('associateFileEntries', 'false')
        if self.checkbox1.isSelected():
            self.local_settings.setSetting('programEntries', 'true')
        else:
            self.local_settings.setSetting('programEntries', 'false')
        if self.checkbox2.isSelected():
            self.local_settings.setSetting('unassociatePrograms', 'true')
        else:
            self.local_settings.setSetting('unassociatePrograms', 'true')


    # TODO: Update this for your UI
    def initComponents(self):
        self.setLayout(BoxLayout(self, BoxLayout.Y_AXIS))
        #self.setLayout(GridLayout(0,1))
        self.setAlignmentX(JComponent.LEFT_ALIGNMENT)
        self.panel1 = JPanel()
        self.panel1.setLayout(BoxLayout(self.panel1, BoxLayout.Y_AXIS))
        self.panel1.setAlignmentY(JComponent.LEFT_ALIGNMENT)
        self.checkbox = JCheckBox("Associate File Entries", actionPerformed=self.checkBoxEvent)
        self.checkbox1 = JCheckBox("Program Entries", actionPerformed=self.checkBoxEvent)
        self.checkbox2 = JCheckBox("Unassociated Programs", actionPerformed=self.checkBoxEvent)
        self.panel1.add(self.checkbox)
        self.panel1.add(self.checkbox1)
        self.panel1.add(self.checkbox2)
        self.add(self.panel1)
		


    # TODO: Update this for your UI
    def customizeComponents(self):
        self.checkbox.setSelected(self.local_settings.getSetting('associateFileEntries') == 'true')
        self.checkbox1.setSelected(self.local_settings.getSetting('programEntries') == 'true')
        self.checkbox2.setSelected(self.local_settings.getSetting('unassociatePrograms') == 'true')

    # Return the settings used
    def getSettings(self):
        return self.local_settings

 
