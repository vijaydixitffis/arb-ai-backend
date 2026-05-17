import re
from typing import List, Dict, Any, Optional
from pathlib import Path


class MarkdownPrincipleParser:
    """Parser for extracting structured principles from markdown files"""
    
    def __init__(self):
        self.principle_pattern = re.compile(r'### ([A-Z]+-\d+)\s*—\s*(.+)')
        self.header_pattern = re.compile(r'#{1,3}\s+(.+)')
    
    def parse_file(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Parse a markdown file and extract structured principles.
        
        Args:
            file_path: Path to the markdown file
            
        Returns:
            List of principle dictionaries with keys:
            - id: Principle ID (e.g., INT-01)
            - title: Principle title
            - statement: Statement text
            - rationale: Rationale text
            - implications: List of implication points
            - items_to_verify: List of verification items
            - category: Category inferred from ID prefix
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return self.parse_content(content)
    
    def parse_content(self, content: str) -> List[Dict[str, Any]]:
        """
        Parse markdown content and extract structured principles.
        
        Args:
            content: Markdown content as string
            
        Returns:
            List of principle dictionaries
        """
        principles = []
        sections = self._split_into_sections(content)
        
        for section in sections:
            principle = self._parse_principle_section(section)
            if principle:
                principles.append(principle)
        
        return principles
    
    def _split_into_sections(self, content: str) -> List[str]:
        """Split content into principle sections based on ### headers"""
        # Split by ### headers
        sections = re.split(r'\n###\s', content)
        
        # Filter out empty sections and the header/intro
        filtered_sections = []
        for section in sections:
            section = section.strip()
            if section and not section.startswith('#'):
                # Add the ### back for consistency
                section = '### ' + section
                filtered_sections.append(section)
        
        return filtered_sections
    
    def _parse_principle_section(self, section: str) -> Optional[Dict[str, Any]]:
        """Parse a single principle section"""
        lines = section.split('\n')
        
        # Extract principle ID and title from first line
        first_line = lines[0].strip()
        match = self.principle_pattern.match(first_line)
        if not match:
            return None
        
        principle_id = match.group(1)
        title = match.group(2)
        
        # Parse the content
        statement = ""
        rationale = ""
        implications = []
        items_to_verify = []
        
        current_section = None
        current_content = []
        
        for line in lines[1:]:
            line = line.strip()
            
            # Check for section headers
            if line.startswith('**Statement**'):
                if current_section:
                    statement, rationale, implications, items_to_verify = self._process_current_section(
                        current_section, current_content, statement, rationale, implications, items_to_verify
                    )
                current_section = 'statement'
                current_content = []
            elif line.startswith('**Rationale**'):
                if current_section:
                    statement, rationale, implications, items_to_verify = self._process_current_section(
                        current_section, current_content, statement, rationale, implications, items_to_verify
                    )
                current_section = 'rationale'
                current_content = []
            elif line.startswith('**Implications**'):
                if current_section:
                    statement, rationale, implications, items_to_verify = self._process_current_section(
                        current_section, current_content, statement, rationale, implications, items_to_verify
                    )
                current_section = 'implications'
                current_content = []
            elif line.startswith('**Items to Verify in Review**'):
                if current_section:
                    statement, rationale, implications, items_to_verify = self._process_current_section(
                        current_section, current_content, statement, rationale, implications, items_to_verify
                    )
                current_section = 'items_to_verify'
                current_content = []
            elif line.startswith('---'):
                # Section separator, ignore
                continue
            elif line:
                # Content line
                current_content.append(line)
        
        # Process the last section
        if current_section:
            statement, rationale, implications, items_to_verify = self._process_current_section(
                current_section, current_content, statement, rationale, implications, items_to_verify
            )
        
        # Determine category from principle ID
        category = self._infer_category(principle_id)
        
        return {
            'id': principle_id,
            'title': title,
            'statement': statement,
            'rationale': rationale,
            'implications': implications,
            'items_to_verify': items_to_verify,
            'category': category
        }
    
    def _process_current_section(self, section: str, content: List[str], 
                                  statement: str, rationale: str, 
                                  implications: List[str], items_to_verify: List[str]) -> tuple:
        """Process accumulated content for a section and return updated values"""
        text = ' '.join(content).strip()
        
        if section == 'statement':
            statement = text
        elif section == 'rationale':
            rationale = text
        elif section == 'implications':
            # Split by bullet points
            for line in content:
                line = line.strip()
                if line.startswith('-'):
                    implications.append(line[1:].strip())
        elif section == 'items_to_verify':
            # Split by checkbox items
            for line in content:
                line = line.strip()
                if line.startswith('-'):
                    # Remove checkbox markers
                    clean_line = line[1:].strip()
                    clean_line = re.sub(r'\[.\]\s*', '', clean_line)
                    items_to_verify.append(clean_line)
        
        return statement, rationale, implications, items_to_verify
    
    def _infer_category(self, principle_id: str) -> str:
        """Infer category from principle ID prefix"""
        prefix = principle_id.split('-')[0]
        
        category_map = {
            'INT': 'General',
            'API': 'API-Based',
            'FILE': 'File-Based',
            'MSG': 'Message-Based',
            'SEC': 'Security',
            'GOV': 'Governance',
            'OPS': 'Operations',
            'G': 'General',
            'B': 'Business',
            'S': 'Security',
            'A': 'Application',
            'SW': 'Software',
            'D': 'Data',
            'I': 'Infrastructure'
        }
        
        return category_map.get(prefix, 'General')
    
    def extract_arb_weight(self, file_path: str) -> Dict[str, str]:
        """
        Extract ARB weights from the quick reference table in the markdown file.
        
        Args:
            file_path: Path to the markdown file
            
        Returns:
            Dictionary mapping principle IDs to ARB weights
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        weights = {}
        
        # Find the quick reference table
        table_match = re.search(r'\| ID \| Principle \| Category \| ARB Weight \|(.+?)(?=\n\n|\Z)', content, re.DOTALL)
        if table_match:
            table_content = table_match.group(1)
            # Parse table rows
            rows = re.findall(r'\| ([A-Z]+-\d+) \| (.+) \| (.+) \| (.+) \|', table_content)
            for row in rows:
                principle_id = row[0]
                weight = row[3].strip()
                weights[principle_id] = weight
        
        return weights


class MarkdownStandardParser:
    """Parser for extracting structured standards from markdown files"""
    
    def __init__(self):
        self.standard_pattern = re.compile(r'### ([A-Z]+-STD-\d+)\s*—\s*(.+)')
    
    def parse_file(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Parse a markdown file and extract structured standards.
        
        Args:
            file_path: Path to the markdown file
            
        Returns:
            List of standard dictionaries with keys:
            - id: Standard ID (e.g., B-STD-01)
            - title: Standard title
            - purpose_scope: Purpose-Scope text
            - standard: The Standard text
            - rationale_context: Rationale-Context text
            - compliance_governance: Compliance-Governance text
            - domain: Domain inferred from ID prefix
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return self.parse_content(content)
    
    def parse_content(self, content: str) -> List[Dict[str, Any]]:
        """
        Parse markdown content and extract structured standards.
        
        Args:
            content: Markdown content as string
            
        Returns:
            List of standard dictionaries
        """
        standards = []
        sections = self._split_into_sections(content)
        
        for section in sections:
            standard = self._parse_standard_section(section)
            if standard:
                standards.append(standard)
        
        return standards
    
    def _split_into_sections(self, content: str) -> List[str]:
        """Split content into standard sections based on ### headers"""
        # Split by ### headers
        sections = re.split(r'\n###\s', content)
        
        # Filter out empty sections and the header/intro
        filtered_sections = []
        for section in sections:
            section = section.strip()
            if section and not section.startswith('#'):
                # Add the ### back for consistency
                section = '### ' + section
                filtered_sections.append(section)
        
        return filtered_sections
    
    def _parse_standard_section(self, section: str) -> Optional[Dict[str, Any]]:
        """Parse a single standard section"""
        lines = section.split('\n')
        
        # Extract standard ID and title from first line
        first_line = lines[0].strip()
        match = self.standard_pattern.match(first_line)
        if not match:
            return None
        
        standard_id = match.group(1)
        title = match.group(2)
        
        # Parse the content
        purpose_scope = ""
        standard_text = ""
        rationale_context = ""
        compliance_governance = []
        
        current_section = None
        current_content = []
        
        for line in lines[1:]:
            line = line.strip()
            
            # Check for section headers
            if line.startswith('**Purpose-Scope**'):
                if current_section:
                    purpose_scope, standard_text, rationale_context, compliance_governance = self._process_current_section(
                        current_section, current_content, purpose_scope, standard_text, rationale_context, compliance_governance
                    )
                current_section = 'purpose_scope'
                current_content = []
            elif line.startswith('**The Standard**'):
                if current_section:
                    purpose_scope, standard_text, rationale_context, compliance_governance = self._process_current_section(
                        current_section, current_content, purpose_scope, standard_text, rationale_context, compliance_governance
                    )
                current_section = 'standard'
                current_content = []
            elif line.startswith('**Rationale-Context**'):
                if current_section:
                    purpose_scope, standard_text, rationale_context, compliance_governance = self._process_current_section(
                        current_section, current_content, purpose_scope, standard_text, rationale_context, compliance_governance
                    )
                current_section = 'rationale_context'
                current_content = []
            elif line.startswith('**Compliance-Governance**'):
                if current_section:
                    purpose_scope, standard_text, rationale_context, compliance_governance = self._process_current_section(
                        current_section, current_content, purpose_scope, standard_text, rationale_context, compliance_governance
                    )
                current_section = 'compliance_governance'
                current_content = []
            elif line.startswith('---'):
                # Section separator, ignore
                continue
            elif line:
                # Content line
                current_content.append(line)
        
        # Process the last section
        if current_section:
            purpose_scope, standard_text, rationale_context, compliance_governance = self._process_current_section(
                current_section, current_content, purpose_scope, standard_text, rationale_context, compliance_governance
            )
        
        # Determine domain from standard ID
        domain = self._infer_domain(standard_id)
        
        return {
            'id': standard_id,
            'title': title,
            'purpose_scope': purpose_scope,
            'standard': standard_text,
            'rationale_context': rationale_context,
            'compliance_governance': compliance_governance,
            'domain': domain
        }
    
    def _process_current_section(self, section: str, content: List[str],
                                  purpose_scope: str, standard_text: str,
                                  rationale_context: str, compliance_governance: List[str]) -> tuple:
        """Process accumulated content for a section and return updated values"""
        
        if section == 'purpose_scope':
            purpose_scope = ' '.join(content).strip()
        elif section == 'standard':
            # Join bullet points with newlines for better formatting
            standard_text = '\n'.join(content).strip()
        elif section == 'rationale_context':
            rationale_context = ' '.join(content).strip()
        elif section == 'compliance_governance':
            # Split by bullet points
            for line in content:
                line = line.strip()
                if line.startswith('-'):
                    compliance_governance.append(line[1:].strip())
        
        return purpose_scope, standard_text, rationale_context, compliance_governance
    
    def _infer_domain(self, standard_id: str) -> str:
        """Infer domain from standard ID prefix"""
        prefix = standard_id.split('-')[0]
        
        domain_map = {
            'B': 'Business',
            'D': 'Data',
            'A': 'Application',
            'T': 'Technology'
        }
        
        return domain_map.get(prefix, 'General')


# Global instances
markdown_parser = MarkdownPrincipleParser()
standards_parser = MarkdownStandardParser()
