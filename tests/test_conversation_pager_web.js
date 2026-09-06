'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {create} = require('../web/static/js/conversation-pager.js');
const page = (ids, cursor = '', total = ids.length) => ({conversations:ids.map(id=>({id})),next_cursor:cursor,has_more:Boolean(cursor),total});

test('pages append in order, deduplicate, and stop at the last page', async () => {
    const requests=[];
    const pages=[page(['a','b'],'one',3),page(['b','c'],'',3)];
    const pager=create({fetchPage: async input=>{requests.push(input);return pages.shift();}});
    await pager.loadMore(); await pager.loadMore(); await pager.loadMore();
    assert.deepEqual(pager.snapshot().items.map(x=>x.id),['a','b','c']);
    assert.equal(requests.length,2);
    assert.deepEqual(requests.map(x=>x.cursor),['','one']);
    assert.equal(requests[0].limit,20);
});
test('concurrent scroll events share one request', async () => {
    let resolve; let count=0;
    const pager=create({fetchPage:()=>{count++;return new Promise(r=>{resolve=r;});}});
    const first=pager.loadMore(); const second=pager.loadMore();
    await Promise.resolve();
    assert.equal(count,1); assert.equal(first,second);
    resolve(page(['a'])); await first;
    assert.equal(pager.snapshot().loading,false);
});
test('failure keeps earlier rows and cursor; retry requests the same next page', async () => {
    let count=0;const cursors=[];
    const pager=create({fetchPage:async ({cursor})=>{cursors.push(cursor);count++;if(count===2)throw Error('offline');return count===1?page(['a'],'next',2):page(['b'],'',2);}});
    await pager.loadMore();await pager.loadMore();
    assert.equal(pager.snapshot().error,'offline');
    assert.deepEqual(pager.snapshot().items.map(x=>x.id),['a']);
    await pager.loadMore();
    assert.deepEqual(cursors,['','next','next']);assert.equal(pager.snapshot().error,'');
});
test('account/search changes ignore stale responses and stale failures', async () => {
    const tasks=[];
    const pager=create({fetchPage: input=>new Promise((resolve,reject)=>tasks.push({input,resolve,reject}))});
    const old=pager.loadMore();await Promise.resolve();
    pager.reset('history');const current=pager.loadMore();await Promise.resolve();
    tasks[0].resolve(page(['private-old'],'next'));await old;
    assert.deepEqual(pager.snapshot().items,[]);assert.equal(pager.snapshot().loading,true);
    tasks[1].resolve(page(['found']));await current;
    assert.equal(tasks[1].input.query,'history');assert.equal(pager.snapshot().items[0].id,'found');
    pager.reset();const failed=pager.loadMore();await Promise.resolve();
    pager.reset('other');tasks[2].reject(Error('stale'));await failed;
    assert.equal(pager.snapshot().error,'');assert.equal(pager.snapshot().query,'other');
});
test('refresh preserves the number of loaded pages and removal adjusts the count', async () => {
    const pages=[page(['a','b'],'1',4),page(['c','d'],'',4),page(['new','a'],'2',5),page(['b','c'],'3',5)];
    const pager=create({pageSize:2,fetchPage:async ()=>pages.shift()});
    await pager.loadMore();await pager.loadMore();await pager.refresh();
    assert.deepEqual(pager.snapshot().items.map(x=>x.id),['new','a','b','c']);
    assert.equal(pager.snapshot().cursor,'3');pager.remove('b');
    assert.equal(pager.snapshot().total,4);assert.equal(pager.snapshot().items.length,3);
});
test('empty result ends pagination; synchronous errors and invalid cursors are retryable', async () => {
    let calls=0;
    const pager=create({fetchPage:()=>{calls++;if(calls===1)throw Error('sync');if(calls===2)return {conversations:[],has_more:true};return page([]);}});
    await pager.loadMore();assert.equal(pager.snapshot().error,'sync');
    await pager.loadMore();assert.match(pager.snapshot().error,/cursor/);
    await pager.loadMore();assert.equal(pager.snapshot().hasMore,false);assert.equal(pager.snapshot().error,'');
});

test('deleting a conversation during a pending page does not restore it', async () => {
    let resolve;
    let calls = 0;
    const pager = create({fetchPage: () => ++calls === 1
        ? page(['a', 'b'], 'next', 3)
        : new Promise(done => { resolve = done; })});
    await pager.loadMore();
    const pending = pager.loadMore();
    await Promise.resolve();
    pager.remove('a');
    resolve(page(['a', 'c'], '', 2));
    await pending;
    assert.deepEqual(pager.snapshot().items.map(item => item.id), ['b', 'c']);
    assert.equal(pager.snapshot().total, 2);
});
