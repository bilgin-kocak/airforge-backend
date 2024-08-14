from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic
import re
import os
from dotenv import load_dotenv
import json
from solcx import compile_standard, install_solc
import asyncio
from pathlib import Path


load_dotenv()  # Load environment variables from .env file

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
CLAUDE_CLIENT = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

# Install specific Solidity version (you can change this to the version you need)
install_solc("0.8.20")

# Path to OpenZeppelin contracts
OPENZEPPELIN_PATH = Path(__file__).parent / "node_modules" / "@openzeppelin"


class ContractRequest(BaseModel):
    description: str

class CompileRequest(BaseModel):
    code: str

def parse_llm_output(output):
    code_match = re.search(r'```solidity(.*?)```', output, re.DOTALL)
    code = code_match.group(1).strip() if code_match else ""
    
    parts = output.split('```')
    first_explanation = parts[0].strip()
    last_explanation = parts[-1].strip()
    
    return code, first_explanation, last_explanation

async def generate_smart_contract(description):
    prompt_template = """
You are a blockchain developer. You have following simple token contract example.
```solidity
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract MyToken is ERC20, Ownable {{
    constructor()
        ERC20("MyToken", "MTK")
        Ownable(msg.sender)
    {{
    }}

    function mint(address to, uint256 amount) public onlyOwner {{
        _mint(to, amount);
    }}
}}
```

Create a Solidity smart contract with the following description: 
{description}
"""

    prompt = prompt_template.format(description=description)
    print(prompt)
    try:
        response = CLAUDE_CLIENT.messages.create(
                    model="claude-3-5-sonnet-20240620",
                    max_tokens=1024,
                    temperature=0,
                    messages=[{"role": "user", "content": prompt}],
                )
        return response.content[0].text.strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate_contract")
async def generate_contract(request: ContractRequest):
    llm_output = await generate_smart_contract(request.description)
    print(llm_output)
    code, first_explanation, last_explanation = parse_llm_output(llm_output)
    
    return {
        "code": code,
        "first_explanation": first_explanation,
        "last_explanation": last_explanation
    }

@app.post("/compile_contract")
async def compile_contract(request: CompileRequest):

    # Remove line // SPDX-License-Identifier: MIT
    request.code = re.sub(r'// SPDX-License-Identifier: MIT', '', request.code)

    # Remove all comments that start with //
    request.code = re.sub(r'//.*', '', request.code)
    
    try:
        # Define import remapping
        import_remappings = [
            f"@openzeppelin={OPENZEPPELIN_PATH}",
        ]

        compiled_sol = compile_standard(
            {
                "language": "Solidity",
                "sources": {"Contract.sol": {"content": request.code}},
                "settings": {
                    "outputSelection": {
                        "*": {
                            "*": ["abi", "metadata", "evm.bytecode", "evm.sourceMap"]
                        }
                    },
                    "remappings": import_remappings,
                }
            },
            solc_version="0.8.20",
            allow_paths=[str(OPENZEPPELIN_PATH)]
        )

        # Extract ABI and bytecode
        contract_data = compiled_sol['contracts']['Contract.sol']
        contract_name = list(contract_data.keys())[0]
        contract_info = contract_data[contract_name]

        return {
            "abi": contract_info['abi'],
            "bytecode": contract_info['evm']['bytecode']['object']
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=os.getenv("PORT", 8000))