import { createContext, useContext } from 'react';
export interface ModelCapability { model_configured:boolean; core_model:string; batch_model:string; paid_fallback:boolean }
export const ModelConfig=createContext<ModelCapability|null>(null);
export const useModelConfig=()=>useContext(ModelConfig);
